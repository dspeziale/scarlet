#!/usr/bin/env python3
"""One-off helper: wrap translatable template text in ``{{ _('...') }}``.

Run from the repository root. Only strings present in the Italian catalogue are wrapped, so the
result is deterministic and reviewable: adding a key to ``app/i18n/it.py`` and re-running the
script extends the coverage. Idempotent.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = ("/help/", "api_docs")


def jinja_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def wrap(path: Path, keys: set[str]) -> int:
    s = path.read_text(encoding="utf-8")
    original = s
    count = 0

    def repl_text(m: re.Match) -> str:
        nonlocal count
        prefix, text, suffix = m.group(1), m.group(2), m.group(3)
        stripped = text.strip()
        if stripped not in keys:
            return m.group(0)
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()) :]
        count += 1
        return f"{prefix}{lead}{{{{ _('{jinja_escape(stripped)}') }}}}{trail}{suffix}"

    # visible text between tags
    s = re.sub(r"(>)([^<>{}]+?)(<)", repl_text, s)

    def repl_attr(m: re.Match) -> str:
        nonlocal count
        attr, value = m.group(1), m.group(2)
        if value.strip() not in keys:
            return m.group(0)
        count += 1
        return f"{attr}=\"{{{{ _('{jinja_escape(value.strip())}') }}}}\""

    s = re.sub(r'\b(title|placeholder|aria-label)="([^"{}]+)"', repl_attr, s)
    if s != original:
        path.write_text(s, encoding="utf-8", newline="\n")
    return count


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT))
    from app.i18n.it import IT

    keys = set(IT)
    total = 0
    for f in glob.glob(str(ROOT / "app" / "templates" / "**" / "*.html"), recursive=True):
        norm = f.replace("\\", "/")
        if any(skip in norm for skip in SKIP):
            continue
        n = wrap(Path(f), keys)
        if n:
            print(f"{n:4d}  {norm.split('/app/templates/')[-1]}")
            total += n
    print(f"{total} strings wrapped")


if __name__ == "__main__":
    main()
