"""Punto di ingresso del container: ``python -m scarlet [serve | <comando> ...]``.

* senza argomenti (o ``serve``): avvia uvicorn con il logging applicativo (JSON su stdout) e la
  gestione di SIGTERM per uno spegnimento ordinato (``stop_grace_period`` nel compose);
* con un altro comando (es. ``alembic upgrade head``): lo esegue al posto del server. E' cio' che
  usa ``appctl`` per le migrazioni (``docker compose run --rm app alembic upgrade head``).
"""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] != "serve":
        os.execvp(args[0], args)  # noqa: S606 - comando esplicito passato dall'operatore/appctl
    host = os.environ.get("SCARLET_BIND_HOST", "0.0.0.0")  # noqa: S104 - dentro il container
    port = int(os.environ.get("SCARLET_BIND_PORT", "8000"))
    workers = int(os.environ.get("SCARLET_WORKERS", "1"))
    uvicorn.run(
        "scarlet.main:app",
        host=host,
        port=port,
        workers=workers,
        log_config=None,  # il logging e' configurato dall'applicazione
        proxy_headers=True,
        forwarded_allow_ips="*",  # dietro il reverse proxy sulla rete docker
        timeout_graceful_shutdown=20,
    )


if __name__ == "__main__":
    main()
