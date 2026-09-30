"""Audit log: una riga per ogni operazione significativa.

Formato (leggibile e facilmente parsabile):

    2026-09-30 10:32:05 user=mario env=production app=scarlet action=deploy version=git-abc123 result=success detail="..."

Il file e' di proprieta' di root con attributo append-only (chattr +a): appctl puo' solo
aggiungere righe. Se il file non e' scrivibile, appctl segnala l'anomalia ma non blocca
l'operazione (la traccia resta comunque in state/history.jsonl per i deployment).
"""

from __future__ import annotations

import getpass
import os
import sys
from datetime import datetime
from pathlib import Path


def current_actor() -> str:
    """Chi sta operando: la pipeline lo dichiara, sudo lo certifica, altrimenti l'utente."""
    explicit = os.environ.get("APPCTL_ACTOR", "").strip()
    if explicit:
        return explicit[:128]
    sudo_user = os.environ.get("SUDO_USER", "").strip()
    if sudo_user:
        return sudo_user
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - ambienti senza passwd
        return "unknown"


class AuditLog:
    def __init__(self, path: Path, app: str, environment: str, actor: str):
        self.path = path
        self.app = app
        self.environment = environment
        self.actor = actor
        self.warned = False

    def record(
        self, action: str, version: str = "-", result: str = "success", detail: str = ""
    ) -> None:
        detail = detail.replace("\n", " ").replace('"', "'")
        line = (
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"user={self.actor} env={self.environment} app={self.app} action={action} "
            f'version={version} result={result} detail="{detail}"\n'
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            if not self.warned:
                print(f"ATTENZIONE: audit log non scrivibile ({self.path}): {exc}", file=sys.stderr)
                self.warned = True
