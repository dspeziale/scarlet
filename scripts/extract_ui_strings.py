#!/usr/bin/env python3
"""List visible UI strings in the Jinja templates that are not yet wrapped in _().

Helper for maintaining app/i18n translations:  python scripts/extract_ui_strings.py [--json out.json]
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def extract() -> list[str]:
    phrases: set[str] = set()
    for f in glob.glob(str(ROOT / "app" / "templates" / "**" / "*.html"), recursive=True):
        norm = f.replace("\\", "/")
        if "/help/" in norm or "api_docs" in norm:
            continue
        s = Path(f).read_text(encoding="utf-8")
        for m in re.finditer(r">([^<>{}]+?)<", s):
            t = m.group(1).strip()
            if len(t) > 1 and re.search("[A-Za-z]{2}", t) and not t.startswith("&"):
                phrases.add(t)
        for m in re.finditer(r'(?:title|placeholder|aria-label)="([^"{}]+)"', s):
            if re.search("[A-Za-z]{2}", m.group(1)):
                phrases.add(m.group(1).strip())
    return sorted(phrases)


if __name__ == "__main__":
    found = extract()
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(
            json.dumps(found, ensure_ascii=False, indent=0), encoding="utf-8"
        )
    else:
        print("\n".join(found))
    print(f"{len(found)} strings", file=sys.stderr)
