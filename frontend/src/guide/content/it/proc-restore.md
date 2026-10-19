---
title: Ripristinare da un backup
summary: Come riportare Scarlet a uno stato salvato in precedenza con restore.sh (verifica, arresto del servizio, ripristino, riavvio).
category: procedures
order: 130
keywords: restore, ripristino, restore.sh, pkm-admin restore, verify-backup, checksum, disaster recovery
related: backup, proc-backup, proc-installare, faq
---

## Quando serve

- Il database di Scarlet è danneggiato o Scarlet non parte più dopo un errore.
- Una modifica errata (utenti cancellati, impostazioni sbagliate) va annullata.
- Devi ricostruire Scarlet su un nuovo server dopo la perdita di quello originale.

> Il ripristino riguarda **solo Scarlet** (database e configurazione). Non ripristina risorse Kubernetes, dati dei Persistent Volume né etcd. Per quelli servono gli strumenti di backup del cluster: vedi [Backup](guide:backup).

## Prerequisiti

- Accesso `sudo` al server Scarlet.
- Il file di backup da ripristinare, già verificato o verificabile.
- Lo script `restore.sh`, installato in `/opt/pkm/current/scripts/restore.sh` (è anche nel pacchetto di rilascio).
- Una finestra di manutenzione: durante il ripristino Scarlet non è disponibile. I carichi di lavoro nel cluster **non** sono toccati.
- Se ripristini su un server nuovo: Scarlet già installato con `install.sh`, preferibilmente nella **stessa versione** del backup o in una più recente.

## Procedura

1. **Avvisa gli utenti** che Scarlet sarà indisponibile per qualche minuto.
2. **Fai un backup dello stato attuale**, anche se difettoso: ti permette di tornare indietro se il ripristino non è quello giusto.

   ```bash
   sudo pkm-admin backup
   ```

3. **Verifica il file da ripristinare.** Se arriva da un altro sistema, copialo prima in `/var/lib/pkm/backups/`.

   ```bash
   sudo pkm-admin verify-backup /var/lib/pkm/backups/<file>
   ```

4. **Esegui il ripristino**:

   ```bash
   sudo /opt/pkm/current/scripts/restore.sh /var/lib/pkm/backups/<file>            # solo il database
   sudo /opt/pkm/current/scripts/restore.sh /var/lib/pkm/backups/<file> --with-config   # anche config.yaml e pkm.env
   ```

   Lo script verifica l'archivio (se la verifica fallisce si ferma senza modificare nulla), chiede conferma (salvo `--yes`), ferma `pkm.service`, conserva il database attuale come `pkm.db.pre-restore-<data>` (e con `--with-config` le copie `.pre-restore` dei file di configurazione), ripristina, sistema permessi e contesti SELinux e riavvia il servizio attendendo che sia pronto. `pkm-admin restore` esegue solo la parte centrale e richiede il servizio già fermo: usa sempre `restore.sh`.
5. **Controlla la configurazione** ripristinata:

   ```bash
   sudo pkm-admin check-config
   systemctl status pkm
   ```

6. **Ricontrolla i riferimenti esterni.** Con `--with-config` il backup ripristina anche `kubeconfig` e certificati TLS presenti in `/etc/pkm`; file indicati con percorsi esterni a `/etc/pkm` e l'accesso al socket Podman devono invece esistere ed essere leggibili dall'utente `pkm` sul server.
7. **Accedi all'interfaccia** e apri [Monitoraggio → Health](app:/monitoring/health).

## Verifica

- `systemctl status pkm` mostra il servizio `active (running)`.
- La pagina [Health](app:/monitoring/health) mostra backend, database, Kubernetes e Podman come Healthy.
- Gli utenti possono accedere con le credenziali valide al momento del backup.
- Le impostazioni in [Impostazioni](app:/settings/system) corrispondono a quelle attese.
- L'[Audit Log](app:/security/audit) è consultabile (contiene gli eventi fino alla data del backup).

## Se qualcosa va storto

- **Checksum non valido**: `restore.sh` si interrompe senza modificare nulla. Usa un altro backup, ad esempio la copia conservata fuori dal server.
- **Il servizio non riparte**: leggi `journalctl -u pkm -n 200` e `/var/log/pkm/pkm.log`. Se l'errore riguarda la versione del database, installa la stessa versione di Scarlet che ha prodotto il backup o una più recente (l'aggiornamento migra il database).
- **Kubernetes Unhealthy dopo il ripristino**: il kubeconfig indicato in configurazione non esiste sul server o non è leggibile dall'utente `pkm` (permessi consigliati 0640 root:pkm).
- **Password dimenticata dopo il ripristino**: `sudo pkm-admin reset-password <utente>`.
- **Vuoi tornare allo stato precedente**: ripristina il backup fatto al passo 2, oppure (servizio fermo) rimetti al suo posto `/var/lib/pkm/pkm.db.pre-restore-<data>` con proprietario `pkm:pkm`.
