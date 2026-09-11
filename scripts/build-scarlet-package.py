#!/usr/bin/env python3
"""Build a SCARLET release package from a source directory.

Usage:
    python scripts/build-scarlet-package.py --source ./examples/podman-app --version 1.0.0 --output ./dist/

The source directory must contain ``manifest.yaml`` (see
docs/APPLICATION_RELEASE_CONTRACT.md). ``--version`` overrides ``version`` (and
``image.tag`` when it is empty or a placeholder) so the same source tree can
produce successive releases. The output is validated with the same validator
SCARLET uses on upload and a ``.sha256`` companion file is written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a SCARLET release package (*.scarlet.tar.gz)"
    )
    parser.add_argument("--source", required=True, help="Source directory containing manifest.yaml")
    parser.add_argument(
        "--version", help="Release version (semantic versioning), overrides manifest.yaml"
    )
    parser.add_argument("--output", default="dist", help="Output directory (default: dist/)")
    parser.add_argument(
        "--no-validate", action="store_true", help="Skip validation of the produced archive"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    from app.deployment.packager import build_package
    from app.errors import ScarletError

    try:
        result = build_package(
            args.source, args.output, version=args.version, validate=not args.no_validate
        )
    except ScarletError as exc:
        print(f"ERROR: {exc.message}", file=sys.stderr)
        errors = getattr(exc, "errors", None) or {}
        for items in errors.values():
            for item in items if isinstance(items, list) else [items]:
                print(f"  - {item}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"package : {result.output_path}")
        print(
            f"app     : {result.manifest.application} {result.manifest.version} ({result.manifest.runtime})"
        )
        print(f"sha256  : {result.checksum_sha256}")
        print(f"size    : {result.size_bytes} bytes, {len(result.members)} members")
        for warning in result.warnings:
            print(f"WARNING : {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
