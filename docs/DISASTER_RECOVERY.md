# Disaster recovery

## 1. Obiettivi (ASSUMPTION A10, da confermare con il business)

| Parametro | Valore proposto | Significato |
|-----------|-----------------|-------------|
| RPO | 24 ore | si può perdere al massimo un giorno di dati (backup notturno); durante i rilasci in produzione il backup pre-migrazione riduce la finestra |
| RTO | 4 ore | tempo per riportare in esercizio l'applicazione su un server nuovo seguendo INSTALLATION.md e ripristinando l'ultimo backup |

Se servono valori più stringenti: replica PostgreSQL (streaming) verso un secondo host, backup
ogni ora, server di riserva già installato (warm standby). Non implementati.

## 2. Cosa si perde se il server viene distrutto

| Elemento | Perso? | Come si recupera |
|----------|--------|------------------|
| codice, Dockerfile, compose, workflow | no | repository GitHub |
| immagini | no | registry GHCR (tutti i tag `git-*` e `v*`) |
| appctl, script server | no | repository (`platform/`) |
| database | **sì**, fino all'ultimo backup off-site | `appctl restore` dall'ultimo `db-*.sql.gz` |
| secrets | sì, se non c'è copia off-site | ricreare (nuove password/token: SECRETS.md §5) oppure `config-*.tar.gz` |
| configurazione server (`app.conf`, `app.env`) | sì | template + `deploy/env/` nel repository, o `config-*.tar.gz` |
| audit log e storico deployment locale | sì | copia off-site; storico su GitHub Environments |
| certificati TLS | sì | riemissione dalla CA aziendale / ACME automatico |
| chiave SSH della pipeline (pubblica) | sì | `add-deploy-key.sh` con la stessa pubblica; **host key nuova** → aggiornare `DEPLOY_SSH_HOST_KEY` |
| credenziali registry sul server | sì | `registry-login.sh` |

Senza copia off-site dei backup (TODO C1), la perdita del server comporta la **perdita del
database**. È il rischio principale evidenziato in ARCHITECTURE_ANALYSIS.md.

## 3. Procedura di recovery (server nuovo)

Tempo stimato: 2-4 ore. Ruoli: amministratore di sistema (root sul nuovo server), release manager
(GitHub), DBA se DB esterno.

1. **Provisioning**: nuovo server con SO supportato, IP/hostname (idealmente gli stessi: evita di
   cambiare `DEPLOY_HOST` e DNS), accesso SSH con chiave dell'amministratore.
2. **Installazione base**: INSTALLATION.md §3-4 (`install-server.sh`). 20 min.
3. **Operatori**: §5.
4. **Applicazione**: §6 (`install-app.sh`). Se disponibile il backup di configurazione:
   ```
   tar -xzf config-<data>.tar.gz -C /opt/apps/scarlet/ && chown -R deploy:deploy /opt/apps/scarlet && chmod 0600 /opt/apps/scarlet/secrets/app.secrets.env
   ```
   altrimenti §7 (config) e nuovi secrets.
5. **Registry**: §8 (`registry-login.sh`).
6. **Pipeline**: §9. La host key del nuovo server è diversa: aggiornare `DEPLOY_SSH_HOST_KEY`
   nell'Environment GitHub; la chiave pubblica della pipeline resta la stessa.
7. **Proxy e TLS**: §10 (ripristinare `sites/` e `certs/` dal backup off-site, o riemettere).
8. **Deploy della versione che era in produzione**: `appctl history` non c'è più; il tag si legge
   su GitHub (Environments → production → ultimo deployment riuscito) o dal `state/current.json`
   nel backup di configurazione:
   ```
   appctl deploy git-<sha12>
   ```
   Il deploy esegue le migrazioni su un DB vuoto: lo schema è pronto.
9. **Restore dati**:
   ```
   appctl restore /path/db-<data>.sql.gz --yes
   ```
10. **Verifica**: `appctl status`, `appctl health`, applicazione via HTTPS, `appctl doctor`.
11. **DNS**: se l'IP è cambiato, aggiornare il record.
12. **Chiusura**: `appctl backup` (primo backup del nuovo server), riattivare la copia off-site,
    registrare l'incidente e i tempi effettivi (aggiornare RPO/RTO se necessario).

## 4. Scenari parziali

| Scenario | Procedura |
|----------|-----------|
| disco dati corrotto, server ok | fermare l'app (`appctl stop`), sostituire/ripulire `data/postgres` (root), `appctl start` (initdb) → `appctl deploy <tag> --force` (schema) → `appctl restore` |
| DB esterno perso | responsabilità del servizio DB; poi `appctl restart`, `appctl health` |
| registry GHCR non disponibile | le immagini già presenti sul server restano usabili (`PULL_POLICY=missing` temporaneo consente deploy/rollback tra le release locali); attendere il ripristino di GitHub |
| GitHub non disponibile | deploy manuale con `appctl deploy <tag>` se l'immagine è già sul server; nessun nuovo build |
| server di development perso | come §3, senza urgenza; non impatta la produzione |
| perdita del repository | remoto GitHub + cloni locali degli sviluppatori; le immagini nel registry restano deployabili |

## 5. Prove periodiche

| Prova | Frequenza | Esito atteso |
|-------|-----------|--------------|
| restore di un backup in development | trimestrale | `appctl health` HEALTHY, dati presenti |
| ricostruzione completa di un server development da zero | annuale | INSTALLATION.md eseguibile entro RTO |
| rollback in produzione (finestra di manutenzione) | a ogni rilascio importante | `appctl rollback` e ritorno in avanti riusciti |
