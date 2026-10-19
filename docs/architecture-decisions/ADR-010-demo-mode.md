# ADR-010: Modalità DEMO

- Data: 2026-10-19
- Stato: Accepted

## Contesto

Sviluppo, test e dimostrazioni devono essere possibili senza un cluster, ma i dati simulati non devono mai essere confusi con un cluster reale.

## Decisione

Provider in memoria (`DemoKubernetes`, `DemoPodman`) con scenari realistici e simulazione delle operazioni. Attivo solo con `mode: demo`, che la validazione della configurazione rifiuta con `environment: production`. Banner viola a righe su ogni pagina, badge DEMO, header `X-PKM-Mode: demo`, righe di log marcate `[DEMO]`.

## Alternative considerate

Mock nel frontend (non esercita il backend); cluster reale obbligatorio per sviluppare (lento, non sempre disponibile).

## Conseguenze

Test API ed end-to-end eseguibili ovunque; impossibile attivare la DEMO in produzione per errore.
