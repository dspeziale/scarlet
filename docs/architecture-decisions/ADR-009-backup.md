# ADR-009: Backup

- Data: 2026-10-19
- Stato: Accepted

## Contesto

Serve un backup affidabile di Scarlet senza presentare come backup del cluster qualcosa che non lo è.

## Decisione

Backup dell'applicazione: DB (SQLite backup API), configurazione, export opzionale e ripulito dei manifest applicativi (mai Secret), `manifest.json` con SHA-256 per file e `.sha256` dell'archivio. Verifica completa (checksum e integrità SQLite). Ripristino solo da CLI (`restore.sh`) a servizio fermo, con copia `.pre-restore` dello stato attuale. Pianificazione con timer systemd.

## Alternative considerate

Restore dalla UI (sostituirebbe il DB del processo in esecuzione); includere etcd o i dati dei volumi (fuori ambito: esistono strumenti dedicati come Velero).

## Conseguenze

Documentato chiaramente cosa non è incluso; la UI mostra i comandi esatti per il ripristino.
