# ADR-002: Backend

- Data: 2026-10-19
- Stato: Accepted

## Contesto

Serve un backend robusto con buon supporto a REST, OpenAPI, SSE, Kubernetes, testing e logging, installabile offline su Oracle Linux 9.7.

## Decisione

Python 3.12 (AppStream di Oracle Linux 9) + FastAPI su uvicorn. Endpoint sincroni (eseguiti nel threadpool) per le chiamate bloccanti a Kubernetes/Podman; async solo per SSE e monitor. Pydantic per validazione e configurazione (pydantic-settings: YAML + variabili d'ambiente). Un solo processo, gestito da systemd; stato condiviso in SQLite.

## Alternative considerate

Go (binario singolo, ottimo client-go, ma tempi di sviluppo maggiori); Node.js (client Kubernetes meno maturo); Django (più pesante del necessario).

## Conseguenze

Dipendenze distribuite come wheel nel pacchetto di release. Rate limiter e operazioni lunghe sono in memoria: corretto per l'esecuzione a processo singolo (documentata).
