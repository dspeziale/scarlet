---
title: Backup
summary: Cosa salva il backup di Scarlet, cosa contiene l'export dei manifest e perché non sostituisce un vero backup del cluster.
category: reliability
order: 90
keywords: backup, restore, ripristino, etcd, velero, export manifest, sqlite, pkm-admin
related: proc-backup, proc-restore, persistent-volume, cluster, alta-disponibilita
---

## In parole semplici

Quando si parla di "backup" in questa applicazione ci sono **tre cose diverse**, ed è importante non confonderle:

| Tipo | Cosa contiene | Chi lo fa |
|---|---|---|
| **Backup di Scarlet** | Il database e la configurazione della console (utenti, ruoli, audit, impostazioni) | Scarlet |
| **Export dei manifest Kubernetes** | Il YAML delle risorse (Deployment, Service, ConfigMap...) | Scarlet, su richiesta |
| **Backup del cluster** | Lo stato completo del cluster (etcd) e i dati dei volumi | Strumenti dedicati (snapshot etcd, Velero), **non** Scarlet |

Il backup di Scarlet protegge la console, non le tue applicazioni. L'export dei manifest aiuta a ricreare le risorse, ma **non contiene i dati**. Per proteggere davvero il cluster serve una soluzione dedicata.

## Dettagli tecnici

**1. Backup dell'applicazione Scarlet**
- Contiene il database SQLite `/var/lib/pkm/pkm.db` e i file di configurazione presenti in `/etc/pkm`: `config.yaml`, `pkm.env`, `kubeconfig` e certificato/chiave TLS (`tls/`). Viene scritto in `/var/lib/pkm/backups` (permessi 0600, contiene segreti) con un checksum SHA-256 per la verifica d'integrità.
- È eseguito periodicamente dal timer systemd `pkm-backup.timer`, oppure a mano con `pkm-admin backup` o `backup.sh`, oppure da [Operazioni → Backup](app:/operations/backup). Il timer esegue un backup ogni giorno alle 02:30 (con un ritardo casuale fino a 15 minuti); in [Impostazioni → Backup](app:/settings/backup) si regolano il numero di backup conservati e l'export dei manifest.
- Si ripristina con `sudo /opt/pkm/current/scripts/restore.sh <file>`: l'archivio viene verificato, il servizio fermato, il database (e con `--with-config` la configurazione) ripristinato e il servizio riavviato.
- Il file contiene configurazione sensibile: conservalo con permessi restrittivi e copialo anche fuori dal server.

**2. Export dei manifest Kubernetes**
- È un archivio di file YAML delle risorse selezionate, letti dall'API server.
- **Non** contiene i dati dei Persistent Volume (file, database delle applicazioni), **non** è uno snapshot di etcd, **non** include lo stato runtime (Pod, eventi) in modo riapplicabile.
- I Secret **non** vengono mai esportati; sono esclusi anche i namespace di sistema (`kube-system`, `kube-public`, `kube-node-lease`).
- Utile per audit, confronto tra ambienti, ricreazione di risorse cancellate per errore. I campi generati (`status`, `metadata.uid`, `resourceVersion`, `managedFields`, `clusterIP` dei Service) sono già rimossi dall'export.

**3. Backup reale del cluster (non fatto da Scarlet)**
- **Snapshot di etcd** (`etcdctl snapshot save`): salva tutti gli oggetti del cluster; si fa sui nodi del control plane ed è responsabilità di chi amministra il cluster.
- **Velero** o strumenti simili: salvano risorse per namespace e i dati dei volumi (snapshot CSI o copia dei file) su storage esterno.
- Database applicativi: usare anche i loro strumenti nativi (dump, replica).

## Esempio

```bash
# Backup Scarlet manuale e verifica
sudo pkm-admin backup
sudo pkm-admin verify-backup /var/lib/pkm/backups/<file>
systemctl list-timers pkm-backup.timer

# Esempio di backup del cluster (fuori da Scarlet, sul control plane)
sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
```

I percorsi dei certificati etcd dipendono dalla distribuzione Kubernetes in uso.

## Cosa può andare storto

- **Credere di avere un backup del cluster** avendo solo il backup di Scarlet o l'export dei manifest.
- **Backup solo locali**: se il disco del server Scarlet si guasta, si perdono anche i backup in `/var/lib/pkm/backups`.
- **Disco pieno**: i backup falliscono; la pagina Health segnala lo spazio libero della directory dati.
- **Backup mai provati**: un restore mai testato non è un backup affidabile.
- **Export riapplicato senza pulizia**: errori di conflitto o immutabilità dei campi.

## Come verificare

- [Operazioni → Backup](app:/operations/backup) mostra gli ultimi backup e il loro esito.
- [Monitoraggio → Health](app:/monitoring/health) segnala problemi di storage e database.
- `pkm-admin verify-backup <file>` controlla l'integrità di un archivio.
- Esegui periodicamente un restore di prova su un server di test.

## Come risolvere

1. Controlla la conservazione in [Impostazioni → Backup](app:/settings/backup) e copia i file su uno storage esterno (`backup.sh --copy-to`).
2. Segui [Eseguire un backup](guide:proc-backup) e [Ripristinare un backup](guide:proc-restore).
3. Concorda con chi gestisce il cluster snapshot di etcd e un backup dei volumi (es. Velero).
4. Libera spazio o sposta i vecchi backup se il disco si riempie.
