---
title: Eseguire un backup
summary: Come salvare database e configurazione di Scarlet, verificare il backup e conservarlo in modo sicuro.
category: procedures
order: 120
keywords: backup, pkm-admin, backup.sh, pkm-backup.timer, sqlite, esportazione manifest, verify-backup
related: backup, proc-restore, proc-installare, faq
---

## Quando serve

- Prima di un aggiornamento di Scarlet (`upgrade.sh` ne prende comunque uno, ma conviene averne uno tuo verificato).
- Prima di modifiche importanti a utenti, ruoli o impostazioni.
- Per controllare che il backup automatico notturno funzioni.

Prima di tutto, chiarisci **cosa** stai salvando (dettagli in [Backup](guide:backup)):

| Tipo | Cosa contiene | Chi lo fa |
|---|---|---|
| Backup applicativo Scarlet | DB SQLite `/var/lib/pkm/pkm.db` + configurazione di Scarlet | Scarlet |
| Esportazione manifest Kubernetes | YAML delle risorse; **non** i dati dei PV, **non** etcd | Scarlet |
| Backup del cluster | snapshot etcd, Velero, backup dei volumi | **non** Scarlet: strumenti del cluster |

Questa procedura riguarda il **backup applicativo Scarlet**.

## Prerequisiti

- Ruolo **Administrator** in Scarlet, oppure accesso `sudo` al server dove Scarlet è installato.
- Spazio libero sufficiente nella directory dati `/var/lib/pkm` (controlla la voce storage in [Monitoraggio → Health](app:/monitoring/health)).
- Una destinazione esterna al server dove copiare i backup (un backup che vive solo sullo stesso disco non protegge da un guasto del disco).

## Procedura

1. **Controlla la configurazione** in [Impostazioni → Backup](app:/settings/backup): numero di backup conservati ed export dei manifest. Il backup automatico è eseguito dal timer systemd `pkm-backup.timer` ogni giorno alle 02:30 (ritardo casuale fino a 15 minuti).
2. **Avvia un backup manuale dall'interfaccia**: in [Operazioni → Backup](app:/operations/backup) avvia un nuovo backup e attendi che compaia nell'elenco con esito positivo.
3. **In alternativa, da shell** sul server:

   ```bash
   sudo pkm-admin backup
   ls -lh /var/lib/pkm/backups/
   ```

   In alternativa `sudo /opt/pkm/current/scripts/backup.sh [--include-manifests] [--copy-to DIR]`: con `--copy-to` copia l'archivio e il suo `.sha256` in `DIR` (ad esempio un mount NFS) e verifica la copia.
4. **Verifica il backup** appena creato (controllo di integrità e checksum):

   ```bash
   sudo pkm-admin verify-backup /var/lib/pkm/backups/<file>
   ```

5. **Copia il backup fuori dal server**, con `backup.sh --copy-to` oppure con `scp` o `rsync` verso uno storage dedicato, mantenendo i permessi ristretti: il backup contiene dati sensibili (utenti, hash delle password, configurazione).
6. **(Facoltativo) Includi i manifest Kubernetes**: seleziona l'opzione di export quando avvii il backup in [Operazioni → Backup](app:/operations/backup) (o usa `--include-manifests`) per avere una copia YAML delle risorse applicative. Non include Secret, dati dei volumi né lo stato di etcd.
7. **Controlla il timer** automatico:

   ```bash
   systemctl list-timers pkm-backup.timer
   systemctl status pkm-backup.timer
   journalctl -u pkm-backup --since today
   ```

## Verifica

- Il backup compare in [Operazioni → Backup](app:/operations/backup) e in `/var/lib/pkm/backups`.
- `pkm-admin verify-backup` termina senza errori.
- Esiste una copia su un sistema diverso dal server Scarlet.
- `systemctl list-timers` mostra la prossima esecuzione di `pkm-backup.timer`.
- Periodicamente (ad esempio ogni trimestre) prova un [ripristino](guide:proc-restore) su un ambiente di test: un backup mai provato non è un backup affidabile.

## Se qualcosa va storto

- **Spazio disco insufficiente**: libera spazio o riduci la conservazione in [Impostazioni → Backup](app:/settings/backup). La pagina Health segnala lo stato Degraded quando lo spazio scarseggia.
- **Permesso negato**: esegui i comandi con `sudo`; i file sono di proprietà dell'utente di sistema `pkm`.
- **`verify-backup` fallisce**: il file è incompleto o alterato. Non usarlo; crea un nuovo backup e controlla i log in `/var/log/pkm/pkm.log` o con `journalctl -u pkm`.
- **Il timer non parte**: abilitalo con `sudo systemctl enable --now pkm-backup.timer`.
- **Ti serve un backup del cluster**: Scarlet non lo fa. Usa snapshot di etcd o uno strumento come Velero, gestiti dall'amministratore del cluster.
