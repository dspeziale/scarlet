# Installazione di un server da zero

Guida passo-passo per preparare un server Linux nuovo (development o production). Ogni comando è
spiegato. Tempo indicativo: 45 minuti.

## 1. Requisiti hardware (ASSUMPTION R6)

| Ambiente | vCPU | RAM | Disco | Note |
|----------|------|-----|-------|------|
| development | 2 | 4 GB | 40 GB | |
| production | 2-4 | 8 GB | 80 GB | disco separato per `/opt/apps` consigliato (snapshot/backup) |

Le immagini pesano ~330 MB ciascuna; `appctl` ne conserva al massimo `KEEP_RELEASES` (5).

## 2. Sistema operativo

Riferimento: **Ubuntu Server 24.04 LTS** (ASSUMPTION A2). Supportati: Ubuntu 22.04, Debian 12,
RHEL 9 / Oracle Linux 9 (i comandi `apt` diventano `dnf`; lo script di installazione li gestisce).

Requisiti: accesso in uscita HTTPS verso `ghcr.io`, `download.docker.com`, i mirror del sistema;
`python3` ≥ 3.10 (presente di default); systemd.

Aggiornare il sistema prima di tutto:

```bash
sudo apt update && sudo apt upgrade -y && sudo reboot
```

## 3. Ottenere i file della piattaforma sul server

Sul server non serve `git` per il funzionamento; serve solo per l'installazione. Due opzioni:

```bash
# a) clone (server con accesso a GitHub)
git clone https://github.com/dspeziale/scarlet.git /tmp/scarlet

# b) copia da un PC (nessun accesso a GitHub dal server)
scp -r platform/ admin@server:/tmp/scarlet/platform
```

## 4. Installazione base del server

```bash
cd /tmp/scarlet/platform/server
sudo ./install-server.sh
```

Opzioni (variabili d'ambiente prima del comando):

| Variabile | Default | Quando usarla |
|-----------|---------|---------------|
| `DOCKER_DATA_ROOT=/data/docker` | (`/var/lib/docker`) | se c'è un disco dati separato: immagini e container vanno lì (root piccola) |
| `APPS_DATA_DIR=/data/apps` | (`/opt/apps`) | idem per le applicazioni: `/opt/apps` diventa un symlink |
| `HARDEN_SSH=0` | `1` | server condivisi con login di dominio (AD/SSSD) in cui non si può disabilitare l'autenticazione con password senza accordo con il sistemista |
| `PROXY=0` | `1` | se il reverse proxy è gestito altrove |

Esempio per il server di development `mv3412` (Oracle Linux 9.7, disco dati su `/data`):

```bash
sudo env HARDEN_SSH=0 DOCKER_DATA_ROOT=/data/docker APPS_DATA_DIR=/data/apps ./install-server.sh
```

Nota Oracle Linux / RHEL: il comando `docker` preinstallato è spesso lo shim di **Podman**
(`podman-docker`). Lo script lo rimuove (Podman resta) e installa Docker Engine dal repository
ufficiale: la piattaforma è verificata su Docker, non su Podman. SELinux in modalità *enforcing*
richiede l'etichettatura delle directory bind-mount (`chcon -Rt container_file_t /data/apps`):
`install-app.sh` lo segnala; su `mv3412` SELinux è *permissive*.

Lo script (idempotente, rieseguibile) esegue in ordine:

| Passo | Cosa fa | Perché |
|-------|---------|--------|
| Docker | installa Docker Engine e Compose dal repository ufficiale Docker, abilita il servizio | versione aggiornata, non quella (vecchia) della distribuzione |
| `daemon.json` | log rotation di default (20 MB × 5), `live-restore` | un container non può riempire il disco; i container restano attivi durante l'aggiornamento di Docker |
| utente `deploy` | utente di sistema senza password, nel gruppo `docker` | è l'unico che parla con Docker; gli operatori non ne hanno bisogno |
| gruppo `appops` | gruppo degli operatori | possono eseguire solo `appctl` |
| directory | `/opt/apps`, `/opt/platform`, `/var/log/apps` | layout standard (ARCHITECTURE.md §5) |
| appctl | copia in `/opt/appctl`, wrapper in `/usr/local/bin/appctl`, gate SSH | CLI operativa |
| sudoers | `%appops ALL=(deploy) NOPASSWD: /usr/local/bin/appctl` | privilegio minimo |
| rete `proxy` + Caddy | rete Docker condivisa e reverse proxy in `/opt/platform/proxy` | TLS e routing per nome |
| systemd | unit e timer `app-backup@` | backup giornaliero |
| SSH | disabilita l'autenticazione con password | solo chiavi |
| firewall | `ufw`/`firewalld`: solo 22, 80, 443 in ingresso | superficie minima |

**Prima di eseguirlo** assicurarsi di avere la propria chiave SSH in `~/.ssh/authorized_keys`
dell'utente amministrativo: dopo lo script le password SSH non funzionano più.

## 5. Operatori

```bash
sudo usermod -aG appops mario     # per ogni operatore (account personale già esistente)
```

Verifica (come operatore, dopo un nuovo login): `appctl --help`.

## 6. Installazione dell'applicazione

```bash
sudo /tmp/scarlet/platform/server/install-app.sh scarlet production ghcr.io/dspeziale/scarlet 8080
```

Argomenti: nome applicazione, ambiente (`development`|`production`), repository immagine, porta
locale. Crea:

```
/opt/apps/scarlet/
├── app.conf                       manifest (da templates/app.conf.production)
├── config/app.env                 DA COMPILARE (passo 7)
├── secrets/app.secrets.env        generato con password e token casuali (0600)
├── releases/ state/ logs/ backups/
└── data/postgres/                 owner uid 999 (PostgreSQL)
/var/log/apps/scarlet/audit.log    root:appops, append-only
```

e abilita `app-backup@scarlet.timer`.

## 7. Configurazione

```bash
# configurazione non sensibile: dal repository
sudo -u deploy cp /tmp/scarlet/deploy/env/production.env /opt/apps/scarlet/config/app.env

# manifest: rivedere e, se serve, impostare PUBLIC_URL (controllo certificato in appctl doctor)
sudo -u deploy nano /opt/apps/scarlet/app.conf

# secrets: generati; con DB esterno modificare SCARLET_DATABASE_URL
sudo -u deploy cat /opt/apps/scarlet/secrets/app.secrets.env
```

## 8. Accesso al registry (pull delle immagini)

Le immagini su GHCR sono private, ma per i deploy dalla pipeline **non serve nulla**: il job passa
il proprio `GITHUB_TOKEN` ad `appctl`, che fa login, pull e logout. Il rollback ai tag già
deployati funziona anche senza registry.

Solo se gli operatori devono scaricare a mano tag nuovi (deploy manuale di emergenza) serve un
token permanente: un utente GitHub tecnico con PAT classic e solo scope `read:packages`
(link precompilato: `https://github.com/settings/tokens/new?scopes=read:packages&description=scarlet-server-pull`).

```bash
sudo -u deploy /tmp/scarlet/platform/server/registry-login.sh ghcr.io <utente-tecnico>
# chiede il token in modo interattivo; lo salva in /home/deploy/.docker/config.json (0600)
```

## 9. Chiave SSH della pipeline

Sul PC dell'amministratore (o in un runner), generare una coppia di chiavi **dedicata** per ambiente:

```bash
ssh-keygen -t ed25519 -N "" -C "github-actions-scarlet-production" -f scarlet-production
```

Sul server registrare la chiave pubblica con forced command:

```bash
sudo /tmp/scarlet/platform/server/add-deploy-key.sh "$(cat scarlet-production.pub)"
ssh-keyscan -t ed25519 <hostname-o-ip-del-server>      # host key per il secret DEPLOY_SSH_HOST_KEY
```

Su GitHub (Settings → Environments → `production`): secrets `DEPLOY_HOST`, `DEPLOY_SSH_KEY`
(contenuto del file privato `scarlet-production`), `DEPLOY_SSH_HOST_KEY` (riga di `ssh-keyscan`).
Dettagli in GITHUB_ACTIONS.md. Poi distruggere la copia locale della chiave privata.

Prova dal PC: `ssh -i scarlet-production deploy@server "appctl --app scarlet status"` deve
rispondere (eventualmente "nessun deployment"); `ssh -i scarlet-production deploy@server bash`
deve essere **rifiutato**.

## 10. Reverse proxy e TLS

```bash
cd /opt/platform/proxy
sudo -u deploy cp sites/scarlet.caddy.example sites/scarlet.caddy
sudo -u deploy nano sites/scarlet.caddy      # nome DNS (R1) e modalita' TLS (R2)
sudo -u deploy docker compose up -d
```

Opzioni TLS nel file del sito: certificato aziendale (`tls /certs/scarlet.crt /certs/scarlet.key`,
file copiati in `/opt/platform/proxy/certs/`), Let's Encrypt automatico (DNS pubblico), oppure
`tls internal` (CA di Caddy, solo dev). Lifecycle dei certificati: SECURITY.md §6.

## 11. Primo deployment

```bash
appctl --app scarlet deploy git-<sha12>       # tag prodotto dalla CI (riepilogo del run)
appctl status
appctl doctor
```

`doctor` deve mostrare tutti PASS (gli WARN su backup e rollback sono normali al primo deploy).

## 12. Verifiche finali (go-live checklist)

- [ ] `appctl status` → RUNNING / HEALTHY, versione e commit attesi
- [ ] `appctl health` → tutte le dipendenze ok
- [ ] `https://<nome-dns>/health` risponde 200 dal browser di un utente
- [ ] `appctl logs --tail 50` mostra i log JSON dell'applicazione
- [ ] `sudo reboot` e, dopo 2 minuti, `appctl status` → RUNNING (restart policy)
- [ ] `appctl backup` crea i file in `backups/`; `systemctl list-timers 'app-backup@*'`
- [ ] deploy dalla pipeline verso questo ambiente riuscito (run verde su GitHub)
- [ ] test di rollback: `appctl rollback` e poi `appctl rollback` di nuovo (torna avanti)
- [ ] `ssh deploy@server bash` rifiutato; operatori senza `docker` (`docker ps` → permesso negato)
- [ ] `sudo lsattr /var/log/apps/scarlet/audit.log` mostra `a` (append-only)
- [ ] copia off-site dei backup configurata (BACKUP.md) oppure TODO tracciato

## 13. Aggiornamenti

* **appctl**: `sudo /tmp/scarlet/platform/server/install-appctl.sh` (dopo aver aggiornato i file);
  richiede solo `python3` ≥ 3.9 (Oracle Linux 9 ha 3.9);
* **Docker**: `sudo apt upgrade` in una finestra di manutenzione (`live-restore` mantiene i
  container attivi); poi `appctl doctor`;
* **sistema**: aggiornamenti di sicurezza automatici consigliati (`unattended-upgrades`).
