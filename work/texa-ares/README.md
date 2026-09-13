# TEXA ARES 118 come pacchetto SCARLET (copia di lavoro)

Questa directory è una **copia di lavoro**: il progetto originale `C:\JobArea\Ised\Codice\texa`
non è stato modificato. Contiene solo ciò che serve a SCARLET per distribuire la webapp:

| File | Origine | Note |
|---|---|---|
| `manifest.yaml` | scritto per SCARLET | traduce `deploy_package/deploy.sh` + `docker-compose.yml` nel contratto SCARLET |
| `application/image.tar.gz` | copia di `texa/deploy_package/texa_ares_webapp-1.0.1.tar.gz` | immagine `webapp-webapp:1.0.1` (`docker save`), ignorata da git |
| `config/texa.env` | chiavi di `deploy_setup/webapp/.env.example` | **solo valori non segreti** |

I segreti (`SECRET_KEY`, `TEXA_CLIENT_SECRET`, `EVENTHUB_CONNECTION_STRING`, `DATABASE_URL`) non sono
in questa directory: vanno inseriti in SCARLET come voci **SECRET** della configurazione, separatamente
per DEV e PROD (valori presi da `texa.dev.env` / `texa.prod.env`, che restano fuori da git).

## Nuova release

1. In `texa`: aggiornare `APP_VERSION` in `config.py`, costruire l'immagine come oggi
   (`build_and_deploy.ps1` produce `deploy_package/texa_ares_webapp-X.Y.Z.tar.gz`).
2. Copiare il tar.gz in `application/image.tar.gz`, aggiornare `version` e `image.tag` nel manifest
   (oppure passare `--version X.Y.Z` al builder: aggiorna entrambi).
3. `python scripts/build-scarlet-package.py --source work/texa-ares --version X.Y.Z --output dist/`
4. Caricare `dist/texa-ares-X.Y.Z.scarlet.tar.gz` in SCARLET → Packages → Upload, poi Deploy.

## Differenze rispetto al deploy attuale

- il container si chiama `texa-ares` (codice applicazione) invece di `texa_ares_webapp`;
- niente `sudo docker`: l'utente SSH deve poter usare Podman/Docker direttamente;
- `~/docker_status.json` (pannello "Info sistema") non è più un bind mount di un file: il manifest
  monta la directory condivisa `shared/data/status` su `/app/status`; il pannello resta vuoto finché
  la webapp non viene adattata a leggere `/app/status/docker_status.json`;
- la configurazione arriva da SCARLET (`shared/config/scarlet.env`) invece che da `~/texa_deploy/texa.*.env`;
- rollback e storico versioni sono gestiti da SCARLET (`releases/<versione>`, link `current`).
