---
title: Domande frequenti
summary: Risposte rapide alle domande più comuni su installazione, accesso, ruoli, metriche, backup e Podman.
category: faq
order: 10
keywords: faq, domande, setup token, password, ruoli, metriche, demo, live, backup, podman socket, tls, certificato
related: introduzione, proc-installare, proc-collegare-kubernetes, proc-collegare-podman, backup, monitoring, troubleshooting
---

## Domande frequenti

### Ho perso il token di setup mostrato a fine installazione. Cosa faccio?

Il token serve solo per il primo accesso al wizard di configurazione. Puoi generarne uno nuovo sul server con `sudo pkm-admin setup-token`. Il token è monouso: dopo aver creato il primo Administrator il wizard non è più accessibile.

### Ho dimenticato la password dell'amministratore.

Un altro Administrator può reimpostarla da [Sicurezza → Utenti](app:/security/users). Se non c'è nessun altro amministratore, sul server esegui `sudo pkm-admin reset-password <utente>`; in alternativa `sudo pkm-admin create-admin` crea un nuovo account Administrator.

### Che differenza c'è tra modalità LIVE e DEMO?

In **LIVE** Scarlet lavora sul cluster e sul Podman reali: l'intestazione mostra un badge verde "LIVE" con il contesto del cluster. In **DEMO** (`mode: demo` in `/etc/pkm/config.yaml`) l'app usa dati di esempio e mostra un banner a strisce "DEMO". La modalità DEMO serve per formazione e prove ed è accettata solo con `environment: development` (con `production` il servizio non parte): non usarla mai in produzione e non prendere decisioni sulla base dei suoi dati.

### Perché vedo "Metriche avanzate non configurate"?

CPU e memoria di pod e nodi arrivano da **metrics-server** (API `metrics.k8s.io`); traffico di rete e storico arrivano da **Prometheus**, se configurato in Impostazioni. Se queste fonti mancano Scarlet lo dice esplicitamente e non inventa valori. Verifica lo stato in [Monitoraggio → Health](app:/monitoring/health).

### Cosa può fare ciascun ruolo?

- **Administrator**: tutto, inclusi utenti, impostazioni, backup/restore e la rivelazione dei valori dei Secret.
- **Operator**: monitoraggio, deploy, scale, restart, rollout, log, troubleshooting, avvio/arresto/riavvio dei container Podman.
- **Viewer**: sola lettura, senza log e senza valori dei Secret.

I permessi sono applicati dal backend: nascondere un pulsante non basta a ottenere un'azione e un'operazione non permessa viene rifiutata.

### Come vedo il valore di un Secret?

I valori sono nascosti per default. Solo un Administrator può rivelarli dalla pagina del Secret e ogni rivelazione viene registrata nell'[Audit Log](app:/security/audit).

### Il backup di Scarlet salva anche le mie applicazioni?

No. Il backup di Scarlet contiene il database dell'applicazione (`/var/lib/pkm/pkm.db`) e la sua configurazione. L'export dei manifest Kubernetes salva lo YAML delle risorse, ma non i dati dei volumi né etcd. Un vero backup del cluster (snapshot di etcd, Velero) va fatto con strumenti dedicati: vedi [Backup](guide:backup).

### Dove si trovano i backup e quando vengono eseguiti?

In `/var/lib/pkm/backups`. Il timer systemd `pkm-backup.timer` li esegue periodicamente; puoi lanciarne uno manuale da [Operazioni → Backup](app:/operations/backup) o con `sudo pkm-admin backup`. Copia i backup anche fuori dal server.

### Perché il browser segnala il certificato come non sicuro?

L'installer genera un certificato autofirmato in `/etc/pkm/tls/`. Va bene per il primo avvio ma va sostituito con un certificato emesso da una CA attendibile per la tua organizzazione. Il passo TLS del wizard e le [impostazioni di sistema](app:/settings/system) aiutano a configurarlo.

### Collegare il socket Podman rootful è rischioso?

Sì, va saputo. L'accesso al socket `/run/podman/podman.sock` equivale ad avere privilegi di root sull'host: chi lo controlla può avviare container privilegiati. L'installer concede l'accesso al gruppo `pkm` (SocketGroup=pkm, SocketMode=0660). Se non serve gestire container di root, usa il socket rootless di un utente dedicato (`/run/user/<uid>/podman/podman.sock`). Vedi [Collegare Podman](guide:proc-collegare-podman).

### Scarlet non vede il cluster Kubernetes. Da dove parto?

Controlla [Monitoraggio → Health](app:/monitoring/health) e [Impostazioni → Kubernetes](app:/settings/kubernetes). Le cause tipiche sono kubeconfig non leggibile dall'utente `pkm` (deve essere, ad esempio, `/etc/pkm/kubeconfig` con permessi 0640 root:pkm), API server non raggiungibile o token scaduto. Puoi controllare la configurazione con `sudo pkm-admin check-config`.

### Quali permessi deve avere Scarlet sul cluster?

Si consiglia un ServiceAccount dedicato: il manifest `deploy/kubernetes/pkm-rbac.yaml` incluso nel pacchetto crea il namespace `pkm-system`, il ServiceAccount `pkm` e i ClusterRole `pkm-operator` (default) e `pkm-readonly`; il kubeconfig si genera con `scripts/make-kubeconfig.sh`. Evita di usare il kubeconfig di cluster-admin personale.

### Le modifiche fatte nel tab YAML sono sicure?

Prima di applicare puoi **validare** con un dry-run lato server (l'API server controlla la risorsa senza salvarla) e vedere il **diff** con lo stato attuale. Applica solo dopo aver letto il diff. Ricorda che modificare a mano risorse gestite da strumenti GitOps può essere sovrascritto.

### Perché lo streaming dei log si è fermato da solo?

Per proteggere server e browser, lo streaming live si interrompe dopo 30 minuti o 20000 righe. Riavvialo dal pulsante; ogni richiesta può leggere al massimo 5000 righe. Per analisi lunghe usa il download.

### Un pod è in CrashLoopBackOff: lo riavvio?

Prima capisci la causa leggendo i log dell'istanza precedente e gli eventi. Un riavvio senza correzione non risolve. Vedi [CrashLoopBackOff](guide:crashloopbackoff) e il [metodo di troubleshooting](guide:troubleshooting).

### Come aggiorno Scarlet a una nuova versione?

Estrai il nuovo pacchetto ed esegui `sudo ./upgrade.sh`. Lo script installa la nuova release in `/opt/pkm/releases/<versione>`, migra il database, riavvia il servizio e verifica la salute; se qualcosa fallisce torna automaticamente alla release precedente. Esegui comunque un backup prima.

### Dove trovo i log di Scarlet?

Nel journal di systemd (`journalctl -u pkm.service`) e nel file `/var/log/pkm/pkm.log`, ruotato dall'applicazione stessa (10 MB × 5 file). Il livello di log si imposta in [Impostazioni → Logging](app:/settings/logging).

### Disinstallare Scarlet cancella i dati?

No: `sudo ./uninstall.sh` rimuove l'applicazione ma conserva dati, configurazione e backup. Solo con `--purge` vengono eliminati anche questi.

### Dove vedo chi ha fatto cosa?

In [Sicurezza → Audit Log](app:/security/audit): ogni azione che modifica risorse, ogni accesso e ogni rivelazione di Secret viene registrata con utente, data e esito.
