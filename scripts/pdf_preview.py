#!/usr/bin/env python3
"""Render PDF pages to PNG so a build can be checked visually.

Usage: python scripts/pdf_preview.py <file.pdf> [out_dir] [pages]
       pages: "1,2,5" or "all" (default: all)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf as fitz


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else pdf.parent / "preview"
    wanted = sys.argv[3] if len(sys.argv) > 3 else "all"
    out.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    pages = range(len(doc)) if wanted == "all" else [int(p) - 1 for p in wanted.split(",")]
    for index in pages:
        page = doc[index]
        pix = page.get_pixmap(dpi=110)
        target = out / f"{pdf.stem}-p{index + 1:02d}.png"
        pix.save(target)
        print(target)
    print(f"pages: {len(doc)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
