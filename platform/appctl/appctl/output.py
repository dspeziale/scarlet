"""Output per l'operatore: chiaro, allineato, senza dettagli Docker superflui."""

from __future__ import annotations

import json
import sys


class Printer:
    def __init__(self, as_json: bool = False, quiet: bool = False):
        self.as_json = as_json
        self.quiet = quiet

    def kv(self, rows: list[tuple[str, object]]) -> None:
        if self.as_json:
            return
        width = max((len(k) for k, _ in rows), default=0) + 1
        for key, value in rows:
            print(f"{(key + ':').ljust(width)} {value}")

    def line(self, text: str = "") -> None:
        if not self.as_json and not self.quiet:
            print(text)

    def step(self, text: str) -> None:
        if not self.as_json and not self.quiet:
            print(f"  -> {text}")

    def warn(self, text: str) -> None:
        print(f"ATTENZIONE: {text}", file=sys.stderr)

    def error(self, text: str, hint: str | None = None) -> None:
        print(f"ERRORE: {text}", file=sys.stderr)
        if hint:
            print(f"        {hint}", file=sys.stderr)

    def json(self, data: object) -> None:
        if self.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        if self.as_json:
            return
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
        print(fmt.format(*headers))
        print("  ".join("-" * w for w in widths))
        for row in rows:
            print(fmt.format(*row))
