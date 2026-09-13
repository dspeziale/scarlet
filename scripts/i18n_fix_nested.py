#!/usr/bin/env python3
"""Repair ``{{ _('x') }}`` placeholders that ended up *inside* another Jinja expression.

The wrapping pass rewrote visible text between tags, which also matched text living inside a
quoted string of an outer ``{{ ... }}`` call (e.g. ``{{ kv('X', '<span>text</span>') }}``).
This turns those into proper concatenations: ``'<span>' ~ _('text') ~ '</span>'``.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTER = re.compile(r"\{\{(?:(?!\}\}).)*?\}\}", re.S)
INNER = re.compile(r"\{\{\s*_\((['\"])(.*?)\1\)\s*\}\}", re.S)


def fix_expression(expr: str) -> str:
    """Inside one outer {{ ... }} expression, turn nested {{ _('x') }} into ~ _('x') ~."""

    def repl(m: re.Match) -> str:
        quote, text = m.group(1), m.group(2)
        other = '"' if quote == "'" else "'"
        return f"{quote} ~ _({other}{text}{other}) ~ {quote}"

    return INNER.sub(repl, expr)


def main() -> None:
    fixed_files = 0
    fixed_spots = 0
    for f in glob.glob(str(ROOT / "app" / "templates" / "**" / "*.html"), recursive=True):
        path = Path(f)
        s = original = path.read_text(encoding="utf-8")

        def outer_repl(m: re.Match) -> str:
            nonlocal fixed_spots
            expr = m.group(0)
            inner = expr[2:-2]
            if "{{" not in inner:
                return expr
            new_inner = fix_expression(inner)
            if new_inner == inner:
                return expr
            fixed_spots += new_inner.count("~ _(")
            return "{{" + new_inner + "}}"

        # apply repeatedly: outer regex is non-greedy, nested braces need a couple of passes
        for _pass in range(3):
            s = OUTER.sub(outer_repl, s)
        # clean up empty concatenations produced when the literal ended right at the boundary
        s = s.replace("'' ~ ", "").replace(" ~ ''", "").replace('"" ~ ', "").replace(' ~ ""', "")
        if s != original:
            path.write_text(s, encoding="utf-8", newline="\n")
            fixed_files += 1
    print(f"fixed {fixed_spots} nested translations in {fixed_files} files")


if __name__ == "__main__":
    main()
