#!/usr/bin/env python3
"""Report user-visible strings that are not routed through the translation layer.

Scans Jinja templates for text nodes outside ``_()`` and JavaScript files for string
literals that reach the DOM (innerHTML/textContent/toast/confirm) without ``S.t()``.
Run it after touching the UI: every hit is either a string to wrap or a false positive
worth silencing with the SKIP lists below.
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "templates"
JS = ROOT / "app" / "static" / "js"

SKIP_TEMPLATES = {"help/guida.html"}  # standalone Italian document
TAG = re.compile(r"<(script|style|pre|code)\b.*?</\1>", re.S | re.I)
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
TAGS = re.compile(r"<[^>]+>", re.S)
WORDS = re.compile(r"[A-Za-z][A-Za-z'’\-]{2,}(?:\s+[A-Za-z'’\-]+)*")
IGNORE = {"SCARLET", "scarlet", "utf", "true", "false", "null", "none"}


def audit_templates() -> list[str]:
    hits = []
    for f in sorted(glob.glob(str(TEMPLATES / "**" / "*.html"), recursive=True)):
        rel = Path(f).relative_to(TEMPLATES).as_posix()
        if rel in SKIP_TEMPLATES:
            continue
        text = Path(f).read_text(encoding="utf-8")
        text = TAG.sub(" ", text)
        text = JINJA.sub(" ", text)
        text = TAGS.sub(" ", text)
        for match in WORDS.finditer(text):
            word = match.group(0).strip()
            if word in IGNORE or len(word) < 4:
                continue
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"{rel}:{line}: {word}")
    return hits


JS_SINK = re.compile(
    r"(?:innerHTML\s*=|textContent\s*=|S\.toast\(|title:\s*|body:\s*|okLabel:\s*|placeholder:\s*)"
    r"\s*(['\"])((?:(?!\1).){4,}?)\1"
)


def audit_js() -> list[str]:
    hits = []
    for f in sorted(glob.glob(str(JS / "**" / "*.js"), recursive=True)):
        rel = Path(f).relative_to(JS).as_posix()
        if rel.startswith("pages/guida"):
            continue
        for i, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
            for match in JS_SINK.finditer(line):
                value = match.group(2)
                if not re.search(r"[A-Za-z]{4}", value) or value.startswith("<") or "/" in value:
                    continue
                hits.append(f"{rel}:{i}: {value}")
    return hits


def main() -> int:
    template_hits = audit_templates()
    js_hits = audit_js()
    for hit in template_hits:
        print("TEMPLATE", hit)
    for hit in js_hits:
        print("JS      ", hit)
    print(f"\ntemplates: {len(template_hits)} untranslated, js: {len(js_hits)} untranslated")
    return 1 if (template_hits or js_hits) else 0


if __name__ == "__main__":
    sys.exit(main())
