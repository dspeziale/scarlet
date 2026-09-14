#!/usr/bin/env python3
"""Costruisce tutti i manuali PDF di SCARLET in docs/pdf/.

    python scripts/build_pdf_docs.py

I font PT Sans Narrow e PT Mono sono in docs/assets/fonts (licenza OFL). La build fallisce
se manca un font o se un testo contiene un carattere che il font non sa disegnare.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_architettura  # noqa: E402
import doc_requisiti_macchine  # noqa: E402

DOCS = [doc_requisiti_macchine, doc_architettura]


def main() -> int:
    for module in DOCS:
        path = module.main()
        size_kb = path.stat().st_size / 1024
        print(f"{path.relative_to(Path(__file__).resolve().parent.parent)}  ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
