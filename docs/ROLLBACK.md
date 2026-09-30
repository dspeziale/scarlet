# Rollback

Il rollback è un'operazione di primo livello: sempre disponibile, senza rebuild, con le immagini
già presenti nel registry (e di norma già sul server).

## 1. Sapere a cosa si può tornare

```
$ appctl version          # "Previous: 0.0.9 (git-9f8e7d6c5b4a)"
$ appctl history          # tutti i tag deployati con esito
```

`previous.json` contiene l'ultima versione diversa da quella corrente che è stata attiva e sana.

## 2. Eseguire il rollback

Alla versione precedente:

```
$ appctl rollback
Rollback di scarlet (production) -> git-9f8e7d6c5b4a
Versione attuale: git-a1b2c3d4e5f6 (0.1.0)
  -> immagine ghcr.io/dspeziale/scarlet:git-9f8e7d6c5b4a gia' presente
  -> avvio i container
  -> verifico health (timeout 180s)

Rollback completato: scarlet 0.0.9 (git-9f8e7d6c5b4a) e' HEALTHY.
Nota: lo schema del database NON viene riportato indietro (docs/ROLLBACK.md).
```

A un tag specifico (anche non più presente sul server: viene scaricato dal registry):

```
$ appctl rollback git-1122334455aa
```

Dalla pipeline: workflow **Rollback** (`rollback.yml`) scegliendo ambiente e, opzionalmente, il tag.
In produzione richiede la stessa approvazione del deploy.

Dopo il rollback, `previous` punta alla versione da cui si è tornati: si può "tornare avanti" con
un altro `appctl rollback`.

## 3. Rollback automatico

`appctl deploy` esegue da solo il rollback quando la nuova versione non supera l'health gate
(container terminato, crash loop, `/health` o `/ready` non OK entro il timeout, `compose up`
fallito). Exit code 4 = rollback riuscito, 7 = anche il rollback è fallito.

Disattivabile con `AUTO_ROLLBACK=false` in `app.conf` o `appctl deploy --no-auto-rollback`
(sconsigliato in produzione).

## 4. Che cosa succede al database

| Situazione | Effetto del rollback | Azione |
|------------|----------------------|--------|
| La versione nuova ha applicato migrazioni **compatibili** (regola expand/contract, DEPLOYMENT.md §3) | nessuno: il codice precedente funziona con lo schema nuovo | nessuna |
| Le migrazioni **non** erano compatibili (colonna rimossa/rinominata) | il codice precedente fallisce (`/ready` OK ma errori applicativi) | ripristinare il backup pre-migrazione (`appctl restore`), perdendo i dati scritti nel frattempo; oppure correggere in avanti |
| La migrazione era fallita a metà (exit 8) | nessun rollback necessario: la versione precedente non è mai stata fermata | far correggere la migrazione; se lo schema è in stato intermedio, `appctl restore` |

`appctl rollback` **non esegue** `alembic downgrade`: il downgrade automatico è più rischioso del
problema che risolve (perdita di dati, script di downgrade raramente testati). Il downgrade resta
un'operazione manuale dello sviluppatore, documentata caso per caso.

Il backup pre-migrazione (produzione) è in `/opt/apps/<app>/backups/db-<data>.sql.gz`.

## 5. Rollback e configurazione

Il rollback riusa la release estratta per quel tag (`releases/<tag>/`), quindi i file compose della
versione precedente; `config/app.env` e i secrets sono quelli attuali del server. Se il rilascio
nuovo aveva richiesto nuove variabili, quelle in più non disturbano la versione vecchia.

## 6. Verifica dopo il rollback

```
appctl status        # Version/Commit attesi
appctl health        # HEALTHY, dependency database ok
appctl logs --tail 100
```

E registrare l'accaduto (ticket) con l'output di `appctl history` e `appctl logs --deploy`.

## 7. Test del rollback

Il rollback è verificato automaticamente:

* unit test (`platform/appctl/tests/test_rollback_lifecycle.py`, `test_deploy.py`);
* test di integrazione con Docker reale (`platform/tests/integration/test_deploy_flow.py`):
  upgrade A→B, rollback a A, deploy di un'immagine unhealthy con rollback automatico, immagine
  che va in crash, rollback a tag non presente localmente.
