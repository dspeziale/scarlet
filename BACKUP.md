# Backup e ripristino

## Cosa viene salvato

Archivio `/var/lib/pkm/backups/pkm-backup-<AAAAMMGG>T<hhmmss>Z[-scheduled].tar.gz` (modo 0600) con file di checksum
`.sha256` accanto:

| Contenuto | Descrizione |
|---|---|
| `pkm.db` | copia consistente a caldo (SQLite backup API) del database: utenti, sessioni, audit log, impostazioni modificate dalla UI, notifiche, cronologia backup |
| `config/config.yaml`, `config/pkm.env`, `config/kubeconfig`, `config/tls/pkm.crt`, `config/tls/pkm.key` | file della directory di configurazione presenti in `/etc/pkm` (**contengono segreti: token Prometheus, token del ServiceAccount, chiave privata TLS**: proteggere l'archivio, che è creato con permessi 0600) |
| `k8s/<namespace>/<tipo>/<nome>.yaml` | solo con *export dei manifest* (`backup.include_manifests: true`, checkbox nella UI o `--include-manifests`): YAML ripuliti (senza `status`, uid, resourceVersion, managedFields, ownerReferences, clusterIP, volumeName) di Namespace, Deployment, StatefulSet, DaemonSet, CronJob, Service, Ingress, ConfigMap, PersistentVolumeClaim, PodDisruptionBudget, HorizontalPodAutoscaler. Esclusi `kube-system`, `kube-public`, `kube-node-lease` |
| `manifest.json` | formato, versione PKM, data, hostname, versione schema DB, contenuti, SHA-256 di ogni file, errori dell'export |

## Cosa NON viene salvato

**Non è un backup del cluster Kubernetes.** Non contiene: etcd, i dati dei volumi persistenti, i **Secret** (mai
esportati), Pod/ReplicaSet/Job, risorse custom, RBAC, lo stato di Podman (container e immagini). Per il cluster usare
snapshot di etcd (`etcdctl snapshot save`) o uno strumento come Velero; per i dati applicativi i backup propri delle applicazioni.
L'export dei manifest serve a ricostruire o confrontare la configurazione delle applicazioni, non a sostituire questi strumenti.

## Pianificazione e retention

- `pkm-backup.timer`: ogni giorno alle 02:30 con ritardo casuale fino a 15 minuti, `Persistent=true` (se il server era
  spento esegue al successivo avvio). Esegue `pkm-admin backup --scheduled` come utente `pkm`.
- Retention: dopo ogni backup restano solo gli ultimi `backup.retention_count` (default 14) archivi creati da PKM.
  Archivi copiati a mano nella directory sono elencati come *external* e non vengono cancellati.

```bash
systemctl list-timers pkm-backup.timer
journalctl -u pkm-backup
```

## Backup manuale

- UI: Operazioni → Backup → "Esegui backup ora" (Administrator), con avanzamento.
- Shell: `sudo /opt/pkm/current/scripts/backup.sh [--include-manifests] [--copy-to DIR]`.
  `--copy-to` copia archivio e `.sha256` in `DIR` (es. un mount NFS) e verifica la copia con `sha256sum -c`.

## Verifica

UI ("Verifica") oppure `sudo pkm-admin verify-backup <file>`. Controlli: checksum dell'archivio (`.sha256`), presenza
di `manifest.json`, checksum di ogni file, `PRAGMA integrity_check` del database estratto, rifiuto di percorsi non
sicuri. Esito `ok: true/false` (exit code 0/1).

## Ripristino

Il ripristino si fa da shell, con il servizio fermo (scelta voluta: sostituire il DB di un servizio in esecuzione non è sicuro):

```bash
sudo /opt/pkm/current/scripts/restore.sh /var/lib/pkm/backups/pkm-backup-20261019T023012Z-scheduled.tar.gz [--with-config] [--yes]
```

1. verifica l'archivio — se fallisce si ferma senza modificare nulla;
2. ferma `pkm.service`;
3. salva il database attuale come `pkm.db.pre-restore-<UTC>` e ripristina quello dell'archivio;
4. con `--with-config` ripristina anche `config.yaml`, `pkm.env`, `kubeconfig` e `tls/` (copie `.pre-restore-<UTC>` dei file attuali; `restore.sh` ripristina proprietario `root:pkm` e permessi 0640, 0644 per il certificato);
5. ripristina proprietari/permessi e contesti SELinux, avvia il servizio e attende che sia pronto.

Kubernetes e Podman non vengono toccati. Le sessioni presenti nel backup restano valide solo se non scadute.

## Copie fuori dal server

Conservare copie degli archivi su un sistema diverso (`backup.sh --copy-to`, rsync, strumento di backup aziendale).
Gli archivi contengono hash delle password, audit, la chiave privata TLS, il token Kubernetes del kubeconfig e i segreti di `pkm.env`: trattarli come dati riservati.

## Prova periodica del ripristino

Almeno trimestralmente: copiare un archivio su un server di prova con PKM installato, `restore.sh --with-config`,
verificare login, utenti, audit e impostazioni, registrare l'esito.

## Disaster recovery (nuovo server)

1. Installare la stessa versione (o successiva) di PKM: `sudo ./install.sh --non-interactive`.
2. Copiare l'archivio e ripristinare: `sudo /opt/pkm/current/scripts/restore.sh <archivio> --with-config --yes`.
3. Certificato/chiave TLS e `/etc/pkm/kubeconfig` sono nell'archivio e vengono ripristinati da `--with-config`
   (se il token del kubeconfig è stato revocato, rigenerarlo con `make-kubeconfig.sh`); l'accesso al socket Podman
   non fa parte del backup: ripeterlo con `install.sh --podman-access`.
4. `systemctl restart pkm`, verificare Health e il badge LIVE.
