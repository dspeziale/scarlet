# Runbook operativo

Procedure pratiche per le situazioni più comuni. Tutti i comandi si eseguono sul server
dell'ambiente interessato con il proprio account (gruppo `appops`). Se il server ospita più
applicazioni aggiungere `--app <nome>`.

Regola generale: **prima osservare** (`status`, `health`, `logs`, `doctor`), **poi agire**
(`restart`, `rollback`), **sempre registrare** (ticket con l'output dei comandi).

---

## L'applicazione non risponde

1. `appctl status` — è RUNNING? Health HEALTHY?
2. `appctl health` — quale livello fallisce? (avviata / viva / pronta / dipendenza `database`)
3. `appctl logs --tail 200` — errori, eccezioni, "connection refused" verso il DB
4. `appctl doctor` — disco, memoria, container db, porta, riavvii
5. Se il problema è una dipendenza (DB non raggiungibile): `appctl logs --all --tail 100`;
   con DB containerizzato `appctl restart` riavvia anche il DB
6. Se l'applicazione è viva ma bloccata: `appctl restart`; se ha perso la configurazione:
   `appctl restart --recreate`
7. Se il problema è iniziato con l'ultimo rilascio (`appctl history`): `appctl rollback`
8. Se dopo restart e rollback non risponde: "Container in crash loop" più sotto; escalation allo
   sviluppatore con `appctl logs --deploy` e `appctl logs --tail 500 > /tmp/log.txt`

Se il reverse proxy risponde 502 ma `appctl health` è HEALTHY: problema di proxy, vedere
"Il proxy risponde 502".

---

## Deployment fallito

Il messaggio della pipeline (o di `appctl deploy`) indica l'exit code.

| Exit | Situazione | Cosa fare |
|------|------------|-----------|
| 3 | immagine non trovata / registry non raggiungibile | verificare il tag nel riepilogo CI; `appctl doctor` (voce Registry); login registry scaduto → `registry-login.sh` (SECRETS.md) |
| 2 | configurazione non valida | leggere il messaggio: file mancante o variabile errata in `app.conf`, `config/app.env`, `secrets/` |
| 8 | migrazione DB fallita | **la versione precedente funziona**. `appctl logs --deploy` per l'errore Alembic; coinvolgere lo sviluppatore; non ritentare a caso |
| 4 | health fallita, **rollback automatico riuscito** | l'applicazione funziona con la versione precedente. Raccogliere `appctl logs --deploy` (contiene la diagnostica e gli ultimi log del container fallito) e aprire un bug |
| 7 | health fallita **e** rollback fallito | **applicazione ferma**: procedura sotto |
| 5 | lock | un altro deploy è in corso: attendere. Se nessun deploy è in corso da > 30 min: vedere TROUBLESHOOTING "Lock orfano" |
| 20/21/22 (pipeline) | SSH non raggiungibile / input errato / smoke test fallito | TROUBLESHOOTING "La pipeline non raggiunge il server" |

### Exit 7: applicazione non disponibile

1. `appctl status` e `appctl logs --deploy`: capire perché anche la versione precedente non parte
   (tipico: porta occupata, disco pieno, DB non sano, secrets corrotti);
2. `appctl doctor`: risolvere ciò che è FAIL (disco, porta, Docker);
3. ritentare: `appctl rollback` (o `appctl deploy <tag precedente>` da `appctl history`);
4. se il DB è il problema: `appctl logs --service db --tail 100`; se corrotto → BACKUP.md restore;
5. se nulla funziona: DISASTER_RECOVERY.md.

Quando fare rollback: sempre, se la versione nuova non è sana e la precedente lo era. Non è una
colpa: è il funzionamento normale del sistema.

---

## Server riavviato

1. attendere 2 minuti (Docker e i container ripartono da soli grazie a `restart: unless-stopped`);
2. `appctl status` → RUNNING / HEALTHY. Se STOPPED: era stato fermato con `appctl stop` prima del
   reboot (comportamento voluto) → `appctl start`;
3. `appctl health` → dipendenze ok;
4. `appctl doctor` → Docker, disco, rete `proxy`;
5. reverse proxy: `curl -k https://localhost/health -H "Host: <nome-dns>"` oppure
   `cd /opt/platform/proxy && sudo -u deploy docker compose ps`;
6. se Docker non è partito (`appctl doctor` → "Docker non raggiungibile"): come root
   `systemctl status docker`, `journalctl -u docker -n 100`, `systemctl start docker`.

---

## Disco pieno

Sintomi: `appctl doctor` → "Disco / 9x% usato"; deploy falliti con "no space left on device".

1. `appctl doctor` mostra le percentuali di `/` e di `/opt/apps/<app>`;
2. cosa occupa spazio (come root): `du -xsh /var/lib/docker /opt/apps/* /var/log 2>/dev/null`;
3. immagini e container non usati: `sudo -u deploy docker system df` e poi
   `sudo -u deploy docker image prune -f` (rimuove solo immagini senza tag; le release in uso
   restano). **Non** usare `docker system prune -a` senza valutare: cancellerebbe le immagini di
   rollback;
4. log di container troppo grandi: la rotazione è già configurata (20 MB × 5); se un container
   fuori standard non la rispetta: `docker inspect <c> --format '{{.HostConfig.LogConfig}}'`;
5. backup vecchi: `ls -la /opt/apps/<app>/backups`; la retention è `BACKUP_KEEP_DAYS`;
6. journal di sistema: `journalctl --vacuum-size=200M`;
7. dopo la pulizia: `appctl health`; se l'app era ferma per il disco pieno: `appctl restart`.

Prevenzione: monitorare `appctl doctor` (WARN a 80%), disco separato per `/opt/apps`.

---

## Container in crash loop

Sintomi: `appctl status` → RESTARTING o riavvii > 0; `appctl health` → "no".

1. `appctl logs --tail 200` — l'errore di avvio è quasi sempre nelle prime righe dopo "Started";
2. cause tipiche:
   * variabile mancante o errata in `config/app.env`/`secrets` → correggere, `appctl restart --recreate`;
   * DB non raggiungibile → `appctl logs --service db --tail 100`; con DB esterno verificare rete/credenziali;
   * migrazioni non applicate (`/ready` 503 "schema non allineato") → `appctl deploy <tag corrente> --force`
     (riesegue le migrazioni) o coinvolgere lo sviluppatore;
   * memoria insufficiente (log "Killed", `appctl doctor` memoria bassa) → aumentare il limite in
     compose (nuovo rilascio) o la RAM del server;
3. se è iniziato con un rilascio: `appctl rollback`;
4. se persiste: `appctl stop`, raccogliere `appctl logs --deploy`, `appctl logs --tail 500`, escalation.

---

## La pipeline non raggiunge il server

1. sul server: `systemctl status ssh` (o `sshd`), firewall (`ufw status`): porta 22 aperta agli IP
   dei runner (o self-hosted runner attivo: `systemctl status actions.runner.*`);
2. chiave: `sudo cat /home/deploy/.ssh/authorized_keys` contiene la chiave con `command=".../appctl-ssh-gate"`;
3. host key: `ssh-keyscan -t ed25519 <host>` coincide con il secret `DEPLOY_SSH_HOST_KEY`
   (dopo una reinstallazione del server cambia!);
4. gate: `sudo journalctl -t appctl-ssh-gate -n 50` mostra i comandi accettati/rifiutati;
5. prova dal PC di un amministratore con la stessa chiave (INSTALLATION.md §9).

---

## Il proxy risponde 502 / certificato non valido

1. `cd /opt/platform/proxy && sudo -u deploy docker compose ps` — Caddy è up?
2. `sudo -u deploy docker compose logs --tail 100` — errori di TLS o "dial tcp: lookup scarlet-app"
   (l'app non è sulla rete `proxy`: `appctl doctor` → "Rete proxy");
3. nome DNS e file `sites/<app>.caddy` coerenti; ricaricare: `sudo -u deploy docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`;
4. certificato scaduto: SECURITY.md §6.

---

## Rotazione di un secret

SECRETS.md §5 (procedura passo-passo per token API, password DB, token registry, chiave SSH).

---

## Ripristino da backup

BACKUP.md §4 (`appctl restore`), DISASTER_RECOVERY.md per la perdita totale del server.
