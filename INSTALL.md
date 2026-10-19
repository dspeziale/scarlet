# Installazione

## Prerequisiti

| Requisito | Dettaglio |
|---|---|
| Server | Oracle Linux 9.7 x86_64, systemd come PID 1, accesso root (sudo) |
| Pacchetti | `tar`, `curl`, `openssl`, `install`, `runuser` (presenti nell'installazione minima); `python3.12` da AppStream (installato automaticamente con `dnf` se manca e il repository è raggiungibile) |
| Rete | porta 8443/tcp (o quella scelta) raggiungibile dai browser; accesso all'API server Kubernetes (di solito 6443/tcp) |
| Kubernetes (opzionale) | kubeconfig di un ServiceAccount dedicato (vedi sotto) |
| Podman (opzionale) | `podman` 4.x/5.x con `podman.socket` |
| Disco | ~300 MB per release + spazio per DB e backup in `/var/lib/pkm` |

Il server **non** ha bisogno di Internet: il pacchetto contiene tutte le dipendenze Python (wheel).

## Creare il pacchetto di release

Su una macchina con Node.js ≥ 20, Python ≥ 3.11 e accesso Internet:

```bash
scripts/build-release.sh            # opzioni: --skip-frontend (usa frontend/dist esistente), --python <interprete>
```

Risultato: `release/pkm-<versione>-linux-x86_64.tar.gz` e `.sha256`. Lo script compila il frontend, crea il wheel `pkm`
(con la UI inclusa), scarica le dipendenze per CPython 3.12 manylinux x86_64 e aggiunge script, unit systemd,
manifest Kubernetes, configurazione d'esempio e documentazione.

## Native installation

```bash
sha256sum -c pkm-1.0.0-linux-x86_64.tar.gz.sha256
tar xzf pkm-1.0.0-linux-x86_64.tar.gz
cd pkm-1.0.0-linux-x86_64
sudo ./install.sh [opzioni]
```

Opzioni di `install.sh`:

| Opzione | Effetto |
|---|---|
| `--port N` | porta di ascolto (default 8443, 8080 con `--no-tls`) |
| `--bind ADDR` | indirizzo di bind (default `0.0.0.0`) |
| `--no-tls` | HTTP in chiaro (solo dietro un reverse proxy TLS o per test) |
| `--kubeconfig PATH` | copia il file in `/etc/pkm/kubeconfig` (0640 root:pkm) |
| `--podman-socket URL` | socket API Podman (default `unix:///run/podman/podman.sock`; `none` disattiva Podman) |
| `--podman-access` / `--no-podman-access` | concede / non concede al gruppo `pkm` l'accesso al socket Podman **rootful** (senza opzione: domanda interattiva, default no) |
| `--no-firewall` | non apre la porta in firewalld |
| `--non-interactive` | nessuna domanda (usa i default) |
| `--force` | consente sistemi RHEL 9 compatibili diversi da Oracle Linux |
| `-h`, `--help` | aiuto |

L'installazione è idempotente: rieseguita mantiene configurazione e dati.

### Cosa fa l'installer

1. Verifica root, sistema operativo (Oracle Linux 9.x, x86_64), systemd, comandi necessari, Python ≥ 3.11 (installa `python3.12` se manca), presenza di Podman, kubeconfig indicato.
2. Crea l'utente di sistema `pkm` (shell `/sbin/nologin`) e le directory (`/opt/pkm`, `/etc/pkm` 0750 root:pkm, `/var/lib/pkm`, `/var/lib/pkm/backups` 0700, `/var/log/pkm`), con `restorecon` per SELinux.
3. Crea `/opt/pkm/releases/<versione>/venv` e installa i wheel inclusi (offline); copia script, unit, docs nella release; aggiorna il symlink `/opt/pkm/current`; installa `/usr/local/bin/pkm-admin`.
4. Se mancano, crea `/etc/pkm/config.yaml` (da `config.example.yaml`, applicando porta, bind, TLS, Podman, kubeconfig) e `/etc/pkm/pkm.env`.
5. Se il TLS è attivo e il certificato non esiste, genera un certificato **self-signed** RSA 3072 (825 giorni, SAN con hostname e IP) in `/etc/pkm/tls/`.
6. Con `--podman-access`: drop-in `/etc/systemd/system/podman.socket.d/10-pkm.conf` (`SocketGroup=pkm`, `SocketMode=0660`) e `systemctl enable --now podman.socket`.
7. Inizializza il database (`pkm-admin migrate`), installa `pkm.service`, `pkm-backup.service`, `pkm-backup.timer`, li abilita e avvia.
8. Se firewalld è attivo (e non c'è `--no-firewall`) apre la porta.
9. Attende `/readyz` (90 s). In caso di errore mostra le ultime righe del journal e, se esisteva, ripristina la release precedente.
10. Se non esistono utenti genera il **token di setup** e stampa il riepilogo:

```text
Installation completed.

Application:
  Scarlet 1.0.0

URL:
  https://server.example.com:8443

Service:
  pkm.service (systemctl status pkm) · backups: pkm-backup.timer · logs: journalctl -u pkm

Status:
  active

Next step:
  Open the dashboard.
  The first access opens the setup wizard. One-time setup token:

      Xq3...

  (regenerate it with: sudo pkm-admin setup-token)
```

### Primo accesso (wizard di installazione)

Al primo accesso il browser apre `/setup`: Benvenuto → Verifica sistema (richiede il token) → Kubernetes (test di
connessione e permessi) → Podman (test) → Autenticazione (primo Administrator) → Monitoraggio (Prometheus opzionale,
test) → Backup (retention) → TLS (stato e istruzioni) → Riepilogo → Test connessione → Completato. I componenti
opzionali non bloccano. Dopo il completamento il token viene cancellato e il wizard non è più accessibile.

Token perso: `sudo pkm-admin setup-token` (solo finché non esistono utenti). In alternativa:
`sudo pkm-admin create-admin --username <nome>`.

## Collegare Kubernetes

Sul cluster (con privilegi di amministratore):

```bash
kubectl apply -f /opt/pkm/current/deploy/kubernetes/pkm-rbac.yaml
sudo /opt/pkm/current/scripts/make-kubeconfig.sh -o /etc/pkm/kubeconfig   # dove kubectl funziona; opzione --context
```

`pkm-rbac.yaml` crea il namespace `pkm-system`, il ServiceAccount `pkm`, il Secret `pkm-token` (token long-lived) e due ClusterRole:

- `pkm-operator` (collegato di default): lettura di tutto ciò che Scarlet mostra + le scritture offerte (workload, Service,
  Ingress, ConfigMap, Secret, PVC, PDB, HPA, namespace/PV create/patch/delete, `nodes` patch per cordon, `pods/eviction` per drain).
- `pkm-readonly`: sola lettura (modificare `roleRef.name` nel ClusterRoleBinding). I pulsanti di scrittura falliscono con "Permessi Kubernetes insufficienti".

Se il kubeconfig è stato generato altrove, copiarlo con `install -m 0640 -o root -g pkm <file> /etc/pkm/kubeconfig`.
Poi: Impostazioni → Kubernetes (percorso `/etc/pkm/kubeconfig`, contesto) oppure `kubernetes.kubeconfig` in `config.yaml` e `systemctl restart pkm`.
Verifica: Monitoraggio → Health → "Kubernetes: Healthy" e badge `LIVE · <contesto>` nell'intestazione.

## Collegare Podman

- **Socket rootful** (container di root): `sudo ./install.sh --podman-access` installa il drop-in e abilita `podman.socket`.
  **Attenzione: chi accede al socket rootful ha di fatto privilegi di root sull'host** (vedi SECURITY.md).
- **Socket rootless** (alternativa più sicura, gestisce solo i container di un utente dedicato):
  ```bash
  loginctl enable-linger <utente>
  sudo -u <utente> XDG_RUNTIME_DIR=/run/user/$(id -u <utente>) systemctl --user enable --now podman.socket
  ```
  Impostare `podman.url: unix:///run/user/<uid>/podman/podman.sock` e dare all'utente `pkm` l'accesso al socket (ad
  esempio ACL `setfacl -m u:pkm:rwx /run/user/<uid>/podman` e sul socket).
- Verifica: Container → intestazione "Runtime: Podman · Connessione: …" e Health → Podman.

## TLS

- Di default l'installer genera un certificato self-signed (il browser mostrerà un avviso).
- Per usare un certificato della propria CA:
  ```bash
  install -m 0644 -o root -g pkm server.crt /etc/pkm/tls/pkm.crt     # certificato + catena intermedia
  install -m 0640 -o root -g pkm server.key /etc/pkm/tls/pkm.key
  restorecon -RF /etc/pkm/tls && systemctl restart pkm
  ```
- **Reverse proxy** (TLS terminato dal proxy, es. nginx sullo stesso host): in `config.yaml`
  `server.host: 127.0.0.1`, `server.port: 8080`, `tls_cert: null`, `tls_key: null`, `trusted_proxies: ["127.0.0.1"]`.
  ```nginx
  server {
    listen 443 ssl;
    server_name pkm.example.com;
    ssl_certificate     /etc/pki/tls/certs/pkm.crt;
    ssl_certificate_key /etc/pki/tls/private/pkm.key;
    location / {
      proxy_pass http://127.0.0.1:8080;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto https;
      proxy_buffering off;            # necessario per log live e notifiche (SSE)
      proxy_read_timeout 1h;
    }
  }
  ```
  Con SELinux: `setsebool -P httpd_can_network_connect 1`.

## Firewall e SELinux

- firewalld: aperto automaticamente dall'installer; manualmente `firewall-cmd --permanent --add-port=8443/tcp && firewall-cmd --reload`.
- SELinux resta in enforcing: il servizio gira come `unconfined_service_t`, i file ricevono i contesti di default con
  `restorecon`. In caso di problemi: `ausearch -m avc -ts recent`.

## Podman deployment

Modalità alternativa all'installazione nativa (usarne una sola).

```bash
podman build -f deploy/podman/Containerfile -t localhost/pkm:1.0.0 .
install -d -m 0750 /etc/pkm /etc/pkm/tls
cp config/config.example.yaml /etc/pkm/config.yaml    # server.host 0.0.0.0, port 8443, database.path /var/lib/pkm/pkm.db
cp .env.example /etc/pkm/pkm.env
chgrp -R 10001 /etc/pkm && chmod 0640 /etc/pkm/config.yaml /etc/pkm/pkm.env
install -m 0644 deploy/podman/pkm.container /etc/containers/systemd/pkm.container
systemctl daemon-reload && systemctl start pkm-container.service
```

- L'immagine (Oracle Linux 9 slim + Python 3.12) gira come uid **10001**, rootfs read-only, `DropCapability=ALL`, `NoNewPrivileges`.
- Volumi: `pkm-data:/var/lib/pkm` (database e backup), `/etc/pkm:/etc/pkm:ro` (configurazione, TLS, kubeconfig leggibili da uid 10001).
- Podman dell'host: decommentare il volume del socket in `pkm.container` (stessa avvertenza di sicurezza).
- Il primo accesso richiede il token: `podman exec pkm pkm-admin setup-token`.
- Il timer di backup non è incluso: pianificare `podman exec pkm pkm-admin backup --scheduled`.

## Aggiornamento

```bash
tar xzf pkm-1.0.1-linux-x86_64.tar.gz && cd pkm-1.0.1-linux-x86_64
sudo ./upgrade.sh          # --yes per non chiedere conferma, --keep N release precedenti da tenere (default 2)
```

Sequenza: backup pre-aggiornamento → installazione della nuova release accanto all'attuale → switch del symlink →
riavvio (le migrazioni del DB avvengono all'avvio) → health check. Se la nuova versione non diventa pronta entro
120 s, **ripristina automaticamente** la release precedente e il database del backup pre-aggiornamento.

## Disinstallazione

```bash
sudo /opt/pkm/current/scripts/uninstall.sh            # rimuove l'applicazione, conserva /etc/pkm, /var/lib/pkm, /var/log/pkm e l'utente
sudo /opt/pkm/current/scripts/uninstall.sh --purge    # cancella anche configurazione, database, BACKUP, log e utente (chiede di digitare 'purge')
```

Opzioni: `--yes`, `--keep-firewall`. Nulla viene rimosso dal cluster Kubernetes o da Podman.

## Checklist di verifica

```bash
systemctl status pkm                 # active (running)
systemctl list-timers pkm-backup.timer
curl -fsk https://127.0.0.1:8443/readyz     # {"status":"ok",...}
sudo pkm-admin check-config
journalctl -u pkm -n 50
```

Nella UI: badge LIVE con il contesto atteso, Monitoraggio → Health senza componenti Unhealthy, Dashboard popolata.
