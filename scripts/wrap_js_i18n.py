#!/usr/bin/env python3
"""One-off helper: wrap user-facing string literals in app/static/js with ``S.t('...')``.

Only literals that (a) exist in the Italian catalogue, (b) are at least five characters long and
(c) sit on a line that builds markup or calls a UI helper (toast/confirm/showError/prompt) are
touched, so status values compared in code (``=== "RUNNING"``) are never rewritten. Idempotent.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_MARKERS = (
    "<",
    "S.toast(",
    "S.confirm(",
    "S.showError(",
    "showError(",
    "prompt(",
    "title:",
    "body:",
    "okLabel:",
    "textContent =",
    "label:",
)
SKIP_BEFORE = (
    "/api/",
    "dataset.",
    "getElementById",
    "querySelector",
    "addEventListener",
    "=== ",
    "!== ",
    ".includes(",
    "localStorage",
)


def wrap_file(path: Path, keys: set[str]) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    count = 0
    out: list[str] = []
    for line in lines:
        if "S.t(" in line or not any(marker in line for marker in UI_MARKERS):
            out.append(line)
            continue

        def repl(m: re.Match, _line: str = line) -> str:
            nonlocal count
            quote, text = m.group(1), m.group(2)
            if text not in keys or len(text) < 5:
                return m.group(0)
            before = _line[: m.start()][-40:]
            if any(skip in before for skip in SKIP_BEFORE):
                return m.group(0)
            count += 1
            return f"S.t({quote}{text}{quote})"

        out.append(re.sub(r"""(["'])((?:[^"'\\]|\\.)*?)\1""", repl, line))
    if count:
        path.write_text("".join(out), encoding="utf-8", newline="\n")
    return count


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from app.i18n.it import IT

    keys = set(IT)
    total = 0
    for f in sorted(glob.glob(str(ROOT / "app" / "static" / "js" / "**" / "*.js"), recursive=True)):
        if f.endswith("scarlet.js") or "swagger" in f:
            continue
        n = wrap_file(Path(f), keys)
        if n:
            print(f"{n:4d}  {Path(f).name}")
            total += n
    print(f"{total} strings wrapped")


if __name__ == "__main__":
    main()
