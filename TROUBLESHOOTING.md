# Troubleshooting

Ogni errore mostrato dalla UI ha un codice e un request id ("Dettagli tecnici"): cercarli con
`journalctl -u pkm | grep <request-id>`. Per i problemi del cluster (CrashLoopBackOff, ImagePullBackOff, Pending…)
usare il Centro Operativo e la Guida integrata (sezione Troubleshooting).

## Il servizio non parte

```bash
systemctl status pkm
journalctl -u pkm -n 80 --no-pager
sudo pkm-admin check-config
```

| Sintomo nel journal | Causa | Soluzione |
|---|---|---|
| `ERROR: invalid configuration:` con l'elenco dei campi | valore non valido in `config.yaml`/`pkm.env` | correggere il campo indicato |
| `mode=demo is not allowed with environment=production` | DEMO in produzione | impostare `mode: live` |
| `server.tls_cert and server.tls_key must be set together` | solo uno dei due | impostarli entrambi o nessuno |
| `[Errno 98] address already in use` | porta occupata | `ss -ltnp \| grep 8443`, cambiare `server.port` |
| `PermissionError` su `/etc/pkm/tls/pkm.key` o `/etc/pkm/kubeconfig` | permessi | `chown root:pkm <file>; chmod 0640 <file>` |
| `unable to open database file` | permessi su `/var/lib/pkm` | `chown -R pkm:pkm /var/lib/pkm` |
| AVC denied in `ausearch -m avc -ts recent` | contesti SELinux | `restorecon -RF /opt/pkm /etc/pkm /var/lib/pkm /var/log/pkm` |
| `start request repeated too quickly` | 5 crash in 5 minuti | risolvere la causa, poi `systemctl reset-failed pkm && systemctl start pkm` |

## Accesso

- **"Utente o password non corretti"**: verificare il nome (non sensibile a maiuscole). Password dimenticata:
  `sudo pkm-admin reset-password <utente>`.
- **Account bloccato** (troppi tentativi): attendere `auth.lockout_minutes` (15) o `sudo pkm-admin unlock <utente>`.
- **"Troppi tentativi di accesso" (429)**: limite di 10 login/minuto per IP o utente; attendere i secondi indicati.
- **Sessione scaduta continuamente**: inattività oltre `auth.session_idle_minutes`; oppure accesso in HTTP con cookie
  `Secure` (impostare TLS o `auth.cookie_secure: false` solo per test).
- **403 "missing or invalid CSRF token"** / **"cross-origin request rejected"**: ricaricare la pagina; dietro un proxy
  verificare che l'header `Host` sia inoltrato (`proxy_set_header Host $host`).
- **Token di setup perso**: `sudo pkm-admin setup-token` (se esistono già utenti, usare `pkm-admin create-admin`).
- **"Cambio password obbligatorio"**: password temporanea impostata da un amministratore; cambiarla dal Profilo.

## Kubernetes

| Codice / messaggio UI | Causa | Soluzione |
|---|---|---|
| `k8s_not_configured` — Kubernetes non configurato | kubeconfig assente, non leggibile, contesto inesistente o integrazione disattivata | Impostazioni → Kubernetes; `ls -l /etc/pkm/kubeconfig` (0640 root:pkm); contesti con `kubectl --kubeconfig /etc/pkm/kubeconfig config get-contexts` |
| `k8s_unavailable` — Impossibile ottenere lo stato del cluster | API server spento, rete/firewall, DNS, certificato TLS non valido | `curl -k https://<api>:6443/version` dal server PKM; controllare firewall e `server:` nel kubeconfig |
| `k8s_timeout` — Kubernetes non risponde in tempo | API server lento o sovraccarico | stato del control plane; aumentare `kubernetes.request_timeout` solo se necessario |
| `k8s_auth_failed` — Credenziali rifiutate (401) | token scaduto/revocato, certificato client scaduto, plugin exec fallito | rigenerare con `make-kubeconfig.sh`; verificare il Secret `pkm-system/pkm-token` |
| `k8s_forbidden` — Permessi Kubernetes insufficienti (403) | il ClusterRole non concede l'operazione | `kubectl auth can-i <verbo> <risorsa> --as=system:serviceaccount:pkm-system:pkm`; riapplicare `pkm-rbac.yaml` (o usare `pkm-operator`) |
| `k8s_not_found` | la risorsa non esiste più (es. Pod ricreato) | aggiornare l'elenco |
| `k8s_conflict` | risorsa già esistente o campi gestiti da un altro strumento | verificare il diff; un Administrator può forzare l'apply |
| `k8s_invalid` | manifest rifiutato dall'API server | leggere i campi elencati (`causes`) |
| `k8s_unsupported` | tipo o apiVersion non serviti dal cluster (es. CronJob su Kubernetes < 1.21) o non gestiti da PKM | aggiornare il cluster o usare l'apiVersion indicata |
| Banner "Dati parziali" | il ServiceAccount non può leggere alcuni tipi | ampliare il ClusterRole o accettare la vista parziale |

## Metriche

- **"Metriche avanzate non configurate"** su CPU/Memoria: metrics-server non installato o non raggiungibile
  (`kubectl top nodes` deve funzionare con le credenziali di PKM; servono `get/list` su `metrics.k8s.io`).
- Storico, rete e occupazione volumi richiedono Prometheus: Impostazioni → Kubernetes → Prometheus URL; il token va in
  `PKM_MONITORING__PROMETHEUS_TOKEN`. Errore `metrics_unavailable` con "not reachable": URL/porta/certificato
  (disattivare `prometheus_verify_tls` solo per CA interne non installate).

## Podman

| Codice | Causa | Soluzione |
|---|---|---|
| `podman_not_configured` | integrazione disattivata o URL non valido | Impostazioni → Podman |
| `podman_unavailable` | socket non attivo o senza permessi | `systemctl status podman.socket`; `ls -l /run/podman/podman.sock` deve mostrare gruppo `pkm` e modo `srw-rw----` (drop-in di `install.sh --podman-access`); `systemctl restart podman.socket` |
| `podman_timeout` | Podman bloccato | `podman ps` da shell, `systemctl restart podman.socket` |
| AVC su `podman.sock` | SELinux | `ausearch -m avc -ts recent`; ripristinare i contesti con `restorecon -v /run/podman/podman.sock` |

## Log

- Lo streaming live si interrompe dopo `logs.stream_max_seconds` (1800 s) o `logs.stream_max_lines` (20000 righe):
  premere di nuovo **Live**. "Troppi stream aperti" = superato `logs.max_concurrent_streams` (20).
- Dietro nginx lo streaming richiede `proxy_buffering off` e `proxy_read_timeout` adeguato.
- "Nessuna riga di log": il container non ha scritto su stdout/stderr; per un container in crash usare "Esecuzione precedente".
- I Viewer non possono leggere i log (permesso `logs.read`).

## Backup e restore

- **Backup fallito**: `journalctl -u pkm-backup`; spazio disco (`df -h /var/lib/pkm`); permessi della directory
  (`/var/lib/pkm/backups` 0700 pkm:pkm). Con l'export dei manifest, gli errori di permesso Kubernetes sono elencati in
  `manifest.json` (`export_errors`) senza far fallire il backup.
- **Restore rifiutato "backup verification failed"**: archivio corrotto o modificato (checksum, file o integrità del DB);
  usare un'altra copia. Nulla è stato modificato.
- **Il servizio non riparte dopo il restore**: il database precedente è in `/var/lib/pkm/pkm.db.pre-restore-<UTC>`;
  ripristinarlo con `cp` (servizio fermo) e `chown pkm:pkm`.

## Aggiornamento

`upgrade.sh` ripristina automaticamente la release precedente e il database pre-aggiornamento se la nuova versione
non diventa pronta; il messaggio indica il backup usato. Analizzare `journalctl -u pkm` e riprovare dopo aver corretto
la causa. Se nemmeno la versione precedente parte: `ls /opt/pkm/releases`, ricollegare `/opt/pkm/current` alla release
voluta e usare `restore.sh` con il backup indicato.

## Browser

- **Avviso sul certificato**: il certificato generato è self-signed; installare quello della CA (INSTALL.md → TLS).
- **Pagina bianca / errori dopo un aggiornamento**: ricaricare forzando (Ctrl+F5); gli asset hanno nomi con hash.
- **"Server non raggiungibile"**: rete o servizio fermo (`systemctl status pkm`).
- **429 "Troppe richieste"**: superato `rate_limit.api_per_minute` (600) — tipicamente script che usano la stessa sessione.

## Banner DEMO in produzione

Non può accadere: con `environment: production` il servizio rifiuta `mode: demo` all'avvio. Se si vede il banner DEMO
si sta usando un'istanza di sviluppo (`environment: development`): verificare URL e `sudo pkm-admin check-config`.
