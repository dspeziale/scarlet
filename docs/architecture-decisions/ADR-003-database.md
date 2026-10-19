# ADR-003: Database

- Data: 2026-10-19
- Stato: Accepted

## Contesto

PKM deve conservare utenti, sessioni, audit, impostazioni, notifiche e cronologia backup; deve essere semplice da installare, salvare e ripristinare.

## Decisione

SQLite in modalità WAL (`/var/lib/pkm/pkm.db`), una connessione per unità di lavoro, migrazioni versionate in `db.py`. Contiene solo lo stato applicativo: lo stato di Kubernetes resta in Kubernetes ed è letto al bisogno (cache di pochi secondi).

## Alternative considerate

PostgreSQL (servizio aggiuntivo da installare, aggiornare e salvare: complessità non giustificata dai volumi); duplicare lo stato del cluster in un DB (dati non aggiornati, nessun beneficio).

## Conseguenze

Backup a caldo con la SQLite backup API; CLI e servizio condividono il DB grazie a WAL. Non adatto a più istanze attive contemporaneamente (non richiesto).
