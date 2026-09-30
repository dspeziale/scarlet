# Deployment

## 1. Flusso standard

| Passo | Chi | Come |
|-------|-----|------|
| 1. Merge su `main` | sviluppatore | pull request approvata |
| 2. CI: lint, test, scansioni, build, scan immagine, test integrazione, push | GitHub Actions (`ci.yml`) | automatico |
| 3. Deploy in **development** | GitHub Actions (`deploy.yml`, environment `development`) | automatico al termine della CI |
| 4. Verifica in development | sviluppatore / QA | applicazione su `APP_URL` dev, `appctl status` |
| 5. Promozione in **production** | release manager | workflow *Promote to production* con il tag |
| 6. Approvazione | approvatori dell'environment `production` | GitHub → Actions → Review deployments |
| 7. Deploy in production | GitHub Actions (`deploy.yml`, environment `production`) | automatico dopo l'approvazione |
| 8. Verifica | operatore | `appctl status`, `appctl health`, applicazione |

Il tag da promuovere è quello stampato nel riepilogo della CI (`git-<sha12>`) oppure un alias
semantico `vX.Y.Z` creato con `release-tag.yml` (vedi §6).

**Nessun push può portare da solo in produzione**: `deploy.yml` con `environment: production` è
raggiungibile solo dal workflow manuale di promozione, protetto da required reviewers.

## 2. Strategia di deploy: recreate con health gate

Con Docker Compose su singolo host, a ogni deploy il container dell'applicazione viene fermato e
ricreato con la nuova immagine. Durante questi secondi (tipicamente 3-10 s) le richieste
ricevono un errore dal reverse proxy.

| Strategia | Downtime | Complessità | Note |
|-----------|----------|-------------|------|
| **Recreate + health gate + auto-rollback** (scelta) | secondi | bassa | nessun requisito aggiuntivo; rollback automatico se la nuova versione non è sana |
| Rolling | ~0 | media | richiede più repliche e un load balancer con health check; Compose non lo fa nativamente |
| Blue/green | ~0 | media-alta | due project compose e switch dell'upstream Caddy; doppia memoria; DB condiviso richiede migrazioni compatibili (già richiesto) |
| Canary | ~0 | alta | pesatura del traffico e metriche: fuori scala per questo contesto |

Evoluzione prevista se il downtime diventa inaccettabile: blue/green con Caddy (ARCHITECTURE.md §9).

### Dettagli che rendono il recreate affidabile

* `stop_grace_period: 30s` e gestione di SIGTERM in uvicorn: le richieste in corso terminano;
* `restart: unless-stopped`: dopo un reboot l'applicazione riparte da sola; dopo `appctl stop` no;
* health gate: il deploy è dichiarato riuscito solo se container healthy **e** `/health` **e**
  `/ready` rispondono 200 entro `HEALTH_TIMEOUT` (120 s dev, 180 s prod);
* rilevamento rapido: se il container termina o va in crash loop il deploy fallisce subito, senza
  attendere il timeout;
* dipendenze: `depends_on: db: condition: service_healthy`;
* rollback automatico alla versione precedente (release già estratta, immagine già presente).

## 3. Migrazioni database

Le migrazioni **non** vengono eseguite dall'applicazione all'avvio. Le esegue `appctl deploy`,
esplicitamente, prima di ricreare i container:

```
docker compose run --rm app alembic upgrade head      # MIGRATE_COMMAND in app.conf
```

Regole:

1. **Compatibilità all'indietro (expand/contract)**: lo schema N+1 deve funzionare con il codice N.
   Aggiungere colonne nullable/con default, nuove tabelle, nuovi indici: sì. Rinominare o
   eliminare colonne usate dal codice N: no (si fa in due rilasci: prima il codice smette di usarle,
   poi si eliminano). Così il rollback applicativo non richiede il downgrade dello schema.
2. In produzione, prima delle migrazioni viene fatto un backup automatico del DB
   (`BACKUP_BEFORE_MIGRATE=true`).
3. Se la migrazione fallisce (`exit 8`), la versione precedente resta in esecuzione: nessun
   container viene toccato.
4. Migrazioni lunghe (tabelle grandi): pianificare una finestra, valutare `CREATE INDEX
   CONCURRENTLY` e migrazioni in più passi.

`/ready` confronta la revisione Alembic applicata con quella attesa dal codice: se un deploy
saltasse le migrazioni (`--skip-migrations`), l'applicazione risulterebbe NOT READY e il deploy
fallirebbe con rollback.

## 4. Configurazione per ambiente

| Cosa | Development | Production |
|------|-------------|------------|
| compose | `compose.yaml` + `compose.db.yaml` + `compose.dev.yaml` | `compose.yaml` + `compose.db.yaml` + `compose.prod.yaml` |
| limiti app | 1 CPU, 384 MB | 2 CPU, 768 MB |
| log | 3×10 MB | 10×20 MB |
| config non sensibile | `deploy/env/development.env` → `config/app.env` | `deploy/env/production.env` → `config/app.env` |
| secrets | generati da `install-app.sh`, propri dell'ambiente | idem, distinti |
| health timeout | 120 s | 180 s |
| backup pre-migrazione | no | sì |
| GitHub Environment | `development` (nessuna approvazione) | `production` (required reviewers) |

Il codice non contiene alcun riferimento all'ambiente: tutto arriva da variabili d'ambiente.

### Database esterno (alternativa ad A7)

1. togliere `compose.db.yaml` da `COMPOSE_FILES` e impostare `DB_SERVICE=` in `app.conf`;
2. impostare `SCARLET_DATABASE_URL` nei secrets verso l'host reale (rete raggiungibile dal
   container: la rete `default` del project compose ha accesso in uscita);
3. il backup del DB passa al DBA; `appctl backup` continua a salvare configurazione e stato.

## 5. Deploy manuale (emergenza o primo deploy)

```
appctl deploy git-a1b2c3d4e5f6
appctl status
appctl health
```

L'operazione è identica a quella della pipeline; l'audit registra l'utente che l'ha eseguita.
In produzione, il deploy manuale va giustificato (non passa dalla verifica "già in development").

## 6. Versioni semantiche

1. aggiornare `VERSION` (es. `0.2.0`) e fare merge su `main`; la CI produce `git-<sha12>`;
2. `git tag v0.2.0 && git push origin v0.2.0`;
3. `release-tag.yml` verifica che `VERSION` coincida e aggiunge l'alias `v0.2.0` alla **stessa**
   immagine (nessun rebuild) e crea una GitHub Release;
4. promuovere in produzione usando `v0.2.0` oppure `git-<sha12>`: sono lo stesso digest.

## 7. Idempotenza

* `appctl deploy` dello stesso tag già attivo e sano non ricrea nulla (exit 0);
* pull, estrazione bundle, `compose up -d` sono idempotenti;
* un deploy interrotto a metà (es. server spento) si recupera rieseguendo lo stesso comando;
* `--force` ricrea i container anche se il tag è già attivo (utile per rileggere config).

## 8. Concorrenza

* GitHub: `concurrency: deploy-<ambiente>` in `deploy.yml` (un deploy per ambiente alla volta, i
  successivi restano in coda) e `promote-production` (una promozione alla volta);
* server: lock esclusivo in `state/.lock` (`flock`); un secondo `appctl deploy` termina con exit 5.

## 9. Che cosa registra ogni deployment

`state/current.json` (e ogni riga di `history.jsonl`):

```json
{
  "application": "scarlet", "environment": "production",
  "image": "ghcr.io/dspeziale/scarlet:git-a1b2c3d4e5f6", "tag": "git-a1b2c3d4e5f6",
  "digest": "ghcr.io/dspeziale/scarlet@sha256:...", "commit": "a1b2c3d4e5f6", "version": "0.1.0",
  "actor": "github-actions:mario", "timestamp": "2026-09-30T10:32:05+02:00",
  "action": "deploy", "result": "success", "detail": "", "duration_s": 25.3
}
```

Lo stesso deployment compare in GitHub (Environments) e, se l'applicazione Scarlet è in esercizio,
può essere registrato nel suo inventario (`POST /api/deployments`), evoluzione prevista.
