# Sicurezza

## 1. Modello dei privilegi

```
operatore (account personale, gruppo appops)
   │  sudo -u deploy /usr/local/bin/appctl <comando>   ← unica regola sudoers
   ▼
deploy (utente di sistema, gruppo docker, nessuna password, shell solo per appctl/pipeline)
   │  appctl: solo operazioni applicative, audit di ogni azione
   ▼
Docker Engine (socket unix locale)

pipeline GitHub ──SSH chiave dedicata──▶ deploy, forced command appctl-ssh-gate
                                          (solo deploy/rollback/status/health/version/history)
```

| Soggetto | Può | Non può |
|----------|-----|---------|
| operatore | `appctl *`, leggere audit log | `docker`, shell come deploy, modificare secrets (solo root/deploy) |
| pipeline | sottocomandi `appctl` in allowlist con argomenti validati (regex) | shell, port forwarding, agent forwarding, altri comandi (`restrict` + gate) |
| deploy | tutto ciò che fa appctl; è nel gruppo docker (equivalente root sull'host) | login con password |
| root | installazione, rotazione secrets, rimozione attributo append-only dell'audit | — |

Trade-off accettato: il gruppo `docker` equivale a root. È confinato a un utente di sistema senza
password, raggiungibile solo da sudo ristretto e da una chiave SSH con forced command. Evoluzione:
rootless Docker (ARCHITECTURE.md §9).

Il socket Docker (`/var/run/docker.sock`) **non è mai** esposto in rete né montato in container.

## 2. Baseline del server (applicata da `install-server.sh`)

| Controllo | Implementazione |
|-----------|-----------------|
| SO aggiornato | aggiornamento prima dell'installazione; `unattended-upgrades` consigliato |
| Docker aggiornato | repository ufficiale Docker; Dependabot non copre il server: pianificare aggiornamenti mensili |
| SSH solo con chiave | `PasswordAuthentication no`, `PermitRootLogin prohibit-password`, no X11/agent/TCP forwarding |
| Firewall | ufw/firewalld: in ingresso solo 22, 80, 443 |
| Porte minime | l'app ascolta solo su `127.0.0.1:APP_PORT`; il DB non pubblica porte; TLS terminato da Caddy |
| Utenti non-root | `deploy` di sistema; operatori personali |
| Log Docker limitati | `daemon.json`: json-file 20 MB × 5, `live-restore`, `no-new-privileges` |
| Audit | `/var/log/apps/<app>/audit.log` append-only (`chattr +a`); journal per sudo, sshd, gate |

## 3. Hardening dei container (`deploy/compose*.yaml`)

| Controllo | app | db |
|-----------|-----|----|
| utente non-root | `10001:10001` (fisso nel Dockerfile) | `999:999` |
| filesystem read-only | `read_only: true`, `/tmp` in tmpfs (64 MB) | no (PostgreSQL scrive nel data dir) ma `/tmp` e `/var/run/postgresql` in tmpfs |
| capabilities | `cap_drop: ALL` | `cap_drop: ALL` |
| no-new-privileges | sì | sì |
| limiti | 1-2 CPU, 384-768 MB, 256 PID, nofile 4096 | 1 CPU, 512 MB, 512 PID |
| restart policy | `unless-stopped` | `unless-stopped` |
| health check | `HEALTHCHECK` nel Dockerfile + `/ready` da appctl | `pg_isready` |
| rete | `default` (project) + `proxy`; porta solo su loopback | solo `default` |
| log | json-file con rotazione | json-file con rotazione |

Il reverse proxy Caddy gira con `cap_drop: ALL` + `NET_BIND_SERVICE`, limiti di risorse, health check.

## 4. Immagine

* multi-stage: l'immagine finale non contiene pip, compilatori, sorgenti di test;
* base `python:3.12-slim-bookworm` con `apt-get upgrade` a ogni build (patch di sicurezza);
  Dependabot propone i nuovi tag; RECOMMENDED: pin del digest;
* nessun secret nell'immagine (verificato: la configurazione arriva solo dall'ambiente; il bundle
  `/deploy` contiene solo file compose e `*.example`);
* label OCI con versione, commit, data: tracciabilità immagine → codice;
* `.dockerignore` esclude `.git`, `.env*`, test, docs.

## 5. Scansioni in CI

| Strumento | Cosa | Quando blocca |
|-----------|------|---------------|
| ruff | lint/format (include regole di sicurezza `S`) | sempre |
| pip-audit | CVE nelle dipendenze Python (`requirements.txt`) | sempre (`--strict`) |
| gitleaks | secrets nel codice e in tutta la storia git | sempre |
| Trivy | CVE nel sistema base e nelle librerie dell'immagine | HIGH/CRITICAL con fix disponibile |
| Dependabot | PR settimanali per pip, Actions, immagini base, compose | — |
| actionlint, shellcheck | correttezza di workflow e script | sempre |

Non inclusi: CodeQL (richiede GitHub Advanced Security su repository privati: RECOMMENDED C2),
secret scanning push protection di GitHub (idem; gitleaks copre il caso in CI).

## 6. TLS e certificati

* HTTPS obbligatorio per l'accesso degli utenti; Caddy redirige HTTP → HTTPS;
* security headers: HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  rimozione header `Server`; l'applicazione aggiunge `X-Content-Type-Options` e `Cache-Control: no-store`;
* modalità certificati (REQUIRED R2):

| Modalità | Rinnovo | Quando |
|----------|---------|--------|
| CA aziendale: `tls /certs/<app>.crt /certs/<app>.key` | manuale: sostituire i file in `/opt/platform/proxy/certs/` e `caddy reload`; scadenza monitorata da `appctl doctor` (WARN < 21 giorni, FAIL < 7) con `PUBLIC_URL` in `app.conf` | rete interna con PKI aziendale |
| ACME (Let's Encrypt) | automatico da Caddy (porta 80/443 raggiungibili da Internet o DNS challenge) | nomi DNS pubblici |
| `tls internal` | automatico (CA locale di Caddy; i client devono fidarsi della CA: `caddy trust`) | development |

Procedura di rinnovo manuale: copiare i nuovi file, `docker compose exec caddy caddy reload
--config /etc/caddy/Caddyfile`, verificare `appctl doctor` o `openssl s_client -connect host:443`.

## 7. Secrets

Vedi SECRETS.md. In sintesi: mai nel repository, nel Dockerfile, nell'immagine, nei log, nei YAML
versionati; GitHub Environments per la pipeline, file `0600` sul server, secrets di development e
production distinti, rotazione documentata.

## 8. Log e dati sensibili

* l'applicazione non registra header, body o token; gli health check non generano log;
* gli errori HTTP sono loggati con path e stato, non con i parametri;
* i log di deploy (`logs/deploy-*.log`) contengono i comandi eseguiti ma non i secrets (i file env
  sono referenziati, non stampati); il gate SSH registra solo il comando appctl.

## 9. Superficie esposta

| Porta | Da | Servizio |
|-------|----|----------|
| 22 | runner GitHub (o self-hosted) e amministratori | sshd |
| 80, 443 | utenti | Caddy |
| 127.0.0.1:8080 | solo locale | app (health/ops) |
| nessuna | — | PostgreSQL, socket Docker |

## 10. Checklist periodica (mensile)

- [ ] `appctl doctor` su ogni server: nessun FAIL
- [ ] aggiornamenti SO e Docker applicati
- [ ] PR Dependabot gestite; immagine ricostruita almeno una volta al mese (patch base)
- [ ] certificati con > 30 giorni di validità
- [ ] `journalctl -t appctl-ssh-gate | grep RIFIUTATO` vuoto o spiegato
- [ ] audit log conservato (retention 90 giorni proposta, C3) e backup off-site funzionante
- [ ] membri di `appops` e approvatori dell'environment `production` ancora corretti
