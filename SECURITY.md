# Sicurezza

## Modello di minaccia (sintesi)

PKM è una console con credenziali potenti verso Kubernetes (ServiceAccount `pkm`) e, se abilitato, verso Podman.
Gli asset da proteggere sono: queste credenziali, la possibilità di modificare il cluster, i valori dei Secret, i log
applicativi, l'integrità dell'audit. Minacce considerate: accesso non autenticato alla porta, furto di sessione, CSRF,
XSS, brute force delle password, escalation di ruolo (UI aggirata chiamando l'API), presa di possesso del primo
avvio, esposizione di segreti in log/audit/backup/repository, uso del servizio compromesso per attaccare l'host.

## Autenticazione

- Utenti locali; password con hash **Argon2id** (`argon2-cffi`, rehash automatico se cambiano i parametri).
- Policy: lunghezza minima `auth.password_min_length` (default 12, massimo 256), almeno 3 classi di caratteri
  (minuscole, maiuscole, cifre, simboli), non deve contenere il nome utente, rifiuto di password comuni.
- Messaggio identico per utente inesistente e password errata; tempo di verifica uniforme (hash fittizio).
- Blocco dopo `auth.login_max_attempts` (5) tentativi falliti per `auth.lockout_minutes` (15); sblocco da UI o `pkm-admin unlock`.
- Rate limit del login: 10 tentativi/minuto per IP e per nome utente (`rate_limit.login_per_minute`), anche per il wizard di setup.
- **Sessioni lato server**: token casuale da 256 bit nel cookie, nel database solo il suo SHA-256; scadenza per
  inattività `auth.session_idle_minutes` (30) e assoluta `auth.session_absolute_hours` (12); revoca di tutte le sessioni
  al cambio/reset password e alla disattivazione; "Chiudi le altre sessioni" nel profilo.
- Cookie: `HttpOnly`, `SameSite=Strict`, `Path=/`; con TLS (o proxy fidato) `Secure` e prefisso **`__Host-`** (`__Host-pkm_session`).
- Password temporanee impostate da un amministratore: cambio obbligatorio al primo accesso (le altre API rispondono 403 finché non avviene).
- **Primo avvio**: il wizard funziona solo finché non esistono utenti e richiede il token monouso stampato da
  `install.sh` (nel DB solo il suo hash); chi raggiunge la porta senza token non può creare l'amministratore.

## CSRF, XSS e header

- Ogni richiesta non GET richiede `X-CSRF-Token` uguale al token della sessione (confronto a tempo costante) e, se
  presente, un header `Origin` coincidente con `Host`.
- Content-Security-Policy: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  (unsafe-inline solo per gli stili richiesti da CodeMirror).
- Altri header: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin`, `Strict-Transport-Security` con TLS,
  `Cache-Control: no-store` sulle API.
- React effettua l'escape dell'output; il Markdown della guida (incluso nel pacchetto) è sanitizzato con DOMPurify.

## Autorizzazione (RBAC)

I permessi sono verificati **nel backend** su ogni endpoint (`require(Perm)`); la UI nasconde solo ciò che non è
consentito. Ogni rifiuto è registrato in audit (`access.denied`).

| Permesso | Viewer | Operator | Administrator |
|---|:-:|:-:|:-:|
| cluster.read, podman.read, monitoring.read | ✓ | ✓ | ✓ |
| logs.read | | ✓ | ✓ |
| workloads.deploy, workloads.scale, workloads.restart, workloads.rollout, pods.delete | | ✓ | ✓ |
| podman.operate (start/stop/restart) | | ✓ | ✓ |
| notifications.ack, backup.read, settings.read | | ✓ | ✓ |
| secrets.read_values, resources.apply, resources.delete, nodes.maintain | | | ✓ |
| podman.manage (rimozione, pull), audit.read, users.manage, settings.manage, backup.manage, maintenance.run | | | ✓ |

Regole aggiuntive: gli Operator possono applicare YAML solo dei tipi applicativi (`workload=True` in `kinds.py`);
Secret e namespace richiedono Administrator; solo un Administrator può forzare un apply in conflitto.
Le operazioni distruttive (eliminazioni non di Pod, scale a 0, restart di Pod non gestiti, drain, stop/rimozione
container, eliminazione di backup/utenti) richiedono conferma esplicita con il nome digitato, verificata anche dal
backend (HTTP 428 `confirmation_required`).

## Audit

Registrati: login (riusciti, falliti, rifiutati), logout, cambi password, gestione utenti, accessi negati, rivelazione
dei Secret, deploy/apply/validate, scale, restart, rollout/rollback, delete, cordon/drain, CronJob, azioni Podman,
download di log e backup, impostazioni (valore precedente e nuovo), backup/verifica/restore, manutenzione, setup e
comandi della CLI. Ogni voce contiene utente, timestamp, azione, risorsa, namespace, esito, IP, user agent,
riferimento di sessione (12 caratteri dell'hash) e request id. I campi `password`, `token`, `data`, `stringData`,
`secret` sono sostituiti da `<redacted>`.

## Segreti

- Valori dei Secret Kubernetes nascosti (`<hidden>`) in API, YAML e JSON; anche l'annotazione
  `last-applied-configuration` viene rimossa. "Mostra i valori" è solo per Administrator ed è registrato.
- Variabili d'ambiente sensibili (PASSWORD/SECRET/TOKEN/KEY) mascherate nell'inspect dei container Podman e nell'analisi delle immagini.
- Credenziali di registry digitate nel wizard di onboarding: usate per una sola richiesta, mai salvate.
- File: `/etc/pkm/config.yaml`, `/etc/pkm/pkm.env`, `/etc/pkm/kubeconfig`, `/etc/pkm/tls/pkm.key` → 0640 root:pkm;
  backup 0600 in una directory 0700. Il token Prometheus va in `pkm.env` (`PKM_MONITORING__PROMETHEUS_TOKEN`) e non viene mai restituito dalla UI.
- Nessun segreto nel repository (`.gitignore` esclude config reali, kubeconfig, chiavi, `.env`); nessuna password di default.

## Kubernetes: privilegio minimo

`deploy/kubernetes/pkm-rbac.yaml` concede solo i verbi usati da PKM. **Non** concede: `nodes/proxy`, `pods/exec`,
`pods/attach`, `pods/portforward`, risorse RBAC (`roles`, `clusterroles`, binding), `serviceaccounts/token`, CRD,
webhook o accesso a etcd. Per una console di sola osservazione usare `pkm-readonly`.

## Podman

**L'accesso al socket Podman rootful equivale ad accesso root sull'host** (si possono avviare container privilegiati
con il filesystem dell'host montato). Per questo `install.sh` lo concede solo con `--podman-access` o conferma
esplicita. Alternativa: socket rootless di un utente dedicato.

## Ispezione delle immagini (wizard di onboarding)

`POST /api/v1/images/inspect` fa sì che il server PKM contatti il registry indicato dall'utente (Registry v2 API).
Per evitare che diventi un mezzo per chiamare servizi interni (SSRF):

- è disponibile solo con il permesso `workloads.deploy` (Operator e Administrator) ed è registrato nell'audit log;
- usa **solo HTTPS**, anche per i redirect (massimo 5), con verifica del certificato e timeout di 10 secondi;
- l'host deve essere un nome valido di registry (`host[:porta]`); non si possono indicare URL arbitrari;
- le credenziali inserite nel wizard sono usate per quella sola richiesta, non vengono salvate né registrate.

In DEMO l'ispezione non effettua alcuna richiesta di rete.

## Rete e TLS

TLS diretto (certificato in `/etc/pkm/tls`, self-signed generato all'installazione da sostituire) oppure dietro reverse
proxy con `server.trusted_proxies` (solo gli IP elencati possono impostare `X-Forwarded-For`). Rate limit API:
600 richieste/minuto per sessione o IP (`rate_limit.api_per_minute`). La health page segnala come Degraded l'uso in
produzione senza TLS.

## Validazione degli input

Modelli Pydantic per tutti i body; nomi Kubernetes validati (DNS-1123); solo i tipi in `kinds.py` sono gestiti; YAML
con `safe_load` (massimo 512 KB e 50 documenti); quantità CPU/memoria, porte, percorsi e riferimenti immagine validati;
i path dei backup sono confinati nella directory dei backup; gli archivi con percorsi non sicuri sono rifiutati;
le query Prometheus sono in whitelist (il browser non può inviare PromQL arbitrario).

## Hardening del servizio (systemd)

`pkm.service`: utente `pkm` non privilegiato, `NoNewPrivileges`, `CapabilityBoundingSet=` vuoto, `ProtectSystem=strict`
con scrittura solo in `/var/lib/pkm` e `/var/log/pkm`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`,
`ProtectKernelTunables/Modules/Logs`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`, `RestrictSUIDSGID`,
`RestrictRealtime`, `RestrictNamespaces`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `LockPersonality`,
`SystemCallArchitectures=native`, `SystemCallFilter=@system-service`, `UMask=0027`.

## Modalità DEMO

I dati simulati non possono essere scambiati per un cluster reale: `mode: demo` con `environment: production` viene
rifiutato all'avvio; in DEMO un banner è sempre visibile e ogni risposta ha `X-PKM-Mode: demo`.

## Segnalare una vulnerabilità

Non aprire issue pubbliche: inviare una segnalazione privata al responsabile del progetto con versione, passi per
riprodurre e impatto. Allegare il request id se pertinente, mai credenziali reali.

## Checklist di hardening

- [ ] Certificato della CA aziendale al posto di quello self-signed.
- [ ] Porta esposta solo alle reti degli operatori (firewalld / ACL di rete).
- [ ] ClusterRole minimo necessario (`pkm-readonly` se non servono scritture).
- [ ] Accesso al socket Podman rootful solo se indispensabile.
- [ ] Almeno due Administrator nominali, nessun account condiviso.
- [ ] Backup copiati fuori dal server (`backup.sh --copy-to`) e restore provato.
- [ ] Retention dell'audit coerente con le policy aziendali.
- [ ] `pkm-admin check-config` senza avvisi; Health senza voci Degraded inattese.
