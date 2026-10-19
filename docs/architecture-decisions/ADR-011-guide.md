# ADR-011: Guida online

- Data: 2026-10-19
- Stato: Accepted

## Contesto

La guida deve far parte del prodotto, essere navigabile, ricercabile, contestuale e sempre allineata alla versione installata.

## Decisione

Articoli Markdown (IT/EN, stesso slug) inclusi nel bundle del frontend, con frontmatter (`title`, `summary`, `category`, `order`, `keywords`, `related`) e sezioni standard. Ricerca full-text lato client; link interni `guide:` e `app:`; collegamenti contestuali per tipo di risorsa (`KIND_GUIDE`) e per problema (`REASON_GUIDE`). Rendering con marked e sanitizzazione DOMPurify.

## Alternative considerate

PDF o wiki esterna (non contestuale, si disallinea dalla versione); contenuti nel database (modifica a runtime non richiesta, complica backup e traduzioni).

## Conseguenze

La guida si aggiorna con il software; aumenta la dimensione del bundle principale.
