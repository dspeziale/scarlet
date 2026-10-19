# ADR-006: Integrazione Podman

- Data: 2026-10-19
- Stato: Accepted

## Contesto

PKM deve gestire anche i container Podman dell'host, tecnologia distinta da Kubernetes.

## Decisione

Livello separato (`pkm/podman/`) che usa l'API REST libpod (`/v4.0.0/libpod/...`, compatibile con Podman 4.x e 5.x) tramite httpx su socket unix (`podman.socket`) o HTTP su rete fidata. La UI dichiara sempre che il runtime è Podman. Il socket rootful è concesso solo esplicitamente (`install.sh --podman-access`) perché equivale ad accesso root; è documentata l'alternativa rootless.

## Alternative considerate

Comando `podman` in subprocess (parsing dell'output, permessi, prestazioni); trattare Podman come un altro cluster (modelli diversi: niente controller né repliche).

## Conseguenze

Funzioni limitate a quelle affidabili via API (log dei container solo in tail, senza streaming). Le statistiche possono essere vuote in ambienti annidati.
