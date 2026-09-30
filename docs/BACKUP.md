# Backup

## 1. Cosa va salvato

| Elemento | Dove | Ricreabile senza backup? | Incluso in `appctl backup` |
|----------|------|--------------------------|----------------------------|
| database applicativo | `/opt/apps/<app>/data/postgres/` | **no** | sì: `db-<data>.sql.gz` (`pg_dump --clean --if-exists`) |
| manifest `app.conf` | `/opt/apps/<app>/app.conf` | sì (template + valori) ma comodo | sì: `config-<data>.tar.gz` |
| configurazione `config/app.env` | `/opt/apps/<app>/config/` | sì (da `deploy/env/` nel repo) | sì |
| secrets | `/opt/apps/<app>/secrets/` | **no** (password DB!) | sì (il tar va protetto) |
| stato e storico deployment | `/opt/apps/<app>/state/` | parzialmente (GitHub Environments) | sì |
| audit log | `/var/log/apps/<app>/audit.log` | no | **no**: copiarlo con il backup di sistema (§5) |
| immagini | registry GHCR | sì (pull) | no |
| release estratte | `/opt/apps/<app>/releases/` | sì (dall'immagine) | no |
| reverse proxy | `/opt/platform/proxy/` (Caddyfile, sites, certs, volume `caddy_data`) | config sì, certificati no | **no**: §5 |
| credenziali registry | `/home/deploy/.docker/config.json` | sì (nuovo login) | no |

## 2. Come funziona `appctl backup`

```
$ appctl backup
Backup creato: /opt/apps/scarlet/backups/db-20260930-020013.sql.gz (48 KB)
Backup creato: /opt/apps/scarlet/backups/config-20260930-020013.tar.gz (6 KB)
Retention: 14 giorni (1 file rimossi)
```

* `pg_dump` eseguito dentro il container `db` con le credenziali del file secrets; formato SQL
  compresso (`--clean --if-exists --no-owner`): ripristinabile con `psql` anche su un PostgreSQL
  diverso della stessa major (16);
* tar di `app.conf`, `config/`, `secrets/`, `state/`;
* file `0600` in `backups/` (`0700`, owner deploy);
* retention: `BACKUP_KEEP_DAYS` (7 dev, 14 prod) — i file più vecchi vengono cancellati;
* audit: riga `action=backup`;
* se il DB non è in esecuzione, il backup DB viene saltato con avviso (la configurazione viene
  salvata comunque).

Pianificazione: `app-backup@<app>.timer` ogni giorno alle 02:00 (± 20 min). Verifica:

```
systemctl list-timers 'app-backup@*'
journalctl -u app-backup@scarlet.service -n 20
appctl doctor        # voce "Ultimo backup DB" (WARN se più vecchio di 2 giorni)
```

Backup automatico aggiuntivo: in produzione `appctl deploy` salva il DB prima di ogni migrazione
(`BACKUP_BEFORE_MIGRATE=true`).

## 3. Con database esterno

Il backup del DB è responsabilità del servizio DB esterno (DBA). `appctl backup` salva comunque
configurazione, secrets e stato. Impostare `DB_SERVICE=` in `app.conf`.

## 4. Ripristino

Solo database (l'applicazione viene fermata e riavviata da appctl):

```
appctl restore db-20260930-020013.sql.gz --yes
```

Il comando: ferma il servizio `app`, esegue `psql` con il dump (che contiene `DROP ... IF EXISTS`),
riavvia l'app, verifica `/health` e `/ready`, registra `action=restore` nell'audit.

Configurazione e secrets (server nuovo o file persi), come root:

```
tar -xzf /path/config-20260930-020013.tar.gz -C /opt/apps/scarlet/
chown -R deploy:deploy /opt/apps/scarlet/{app.conf,config,secrets,state}
chmod 0600 /opt/apps/scarlet/secrets/app.secrets.env
```

Test di ripristino: eseguire un restore in development almeno ogni trimestre e verificare con
`appctl health` e con l'applicazione.

## 5. Copia off-site (TODO C1)

I backup in `backups/` sono **sullo stesso disco del server**: proteggono da errori applicativi e
migrazioni sbagliate, non dalla perdita del server. Serve una copia esterna.

Fino a quando la destinazione non è definita, il compito è un **TODO esplicito** con questa
struttura pronta:

```bash
# /etc/cron.daily/apps-offsite (esempio, da adattare alla destinazione: NFS, S3, rsync su altro host)
#!/bin/bash
set -e
DEST="backup-host:/backup/$(hostname)"          # TODO
for app in /opt/apps/*/; do
  rsync -a --delete "$app/backups/" "$DEST/$(basename "$app")/backups/"
done
rsync -a /var/log/apps/ "$DEST/audit/"
rsync -a /opt/platform/proxy/ "$DEST/proxy/"     # include certs/: proteggere la destinazione
```

Requisiti della destinazione: cifratura a riposo o trasporto sicuro (i backup contengono secrets),
accesso in sola scrittura dal server (un server compromesso non deve poter cancellare i backup
remoti), retention ≥ 30 giorni, verifica mensile di un restore.

## 6. Retention riepilogativa

| Cosa | Locale | Off-site (proposta) |
|------|--------|---------------------|
| dump DB giornaliero | 7 giorni dev / 14 prod | 30 giorni + 1 mensile per 12 mesi |
| dump pre-migrazione | come sopra | come sopra |
| config/secrets/stato | come sopra | come sopra |
| audit log | illimitato sul server (rotazione: TODO C3, proposta 90 giorni con `logrotate` copytruncate **non** compatibile con `chattr +a`: usare rotazione per file mensile) | 12 mesi |
