#!/usr/bin/env bash
# Build the offline release tarball for Oracle Linux 9 x86_64:
#   release/pkm-<version>-linux-x86_64.tar.gz (+ .sha256)
#
# Requirements on the build machine: Node.js >= 20 with npm, Python >= 3.11 with pip, internet access
# (dependency wheels are downloaded for the target platform: CPython 3.12, manylinux x86_64).
# The target server needs NO internet access: install.sh installs from the bundled wheels.
#
#   scripts/build-release.sh [--skip-frontend] [--python python3]
set -o errexit -o nounset -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
SKIP_FE=no
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-frontend) SKIP_FE=yes; shift ;;
    --python) PY="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
done
command -v "$PY" >/dev/null || PY=python

VERSION="$("$PY" -c "import re,sys; print(re.search(r'__version__ = \"([^\"]+)\"', open(sys.argv[1]).read()).group(1))" "$REPO/backend/pkm/__init__.py")"
NAME="pkm-$VERSION-linux-x86_64"
OUT="$REPO/release"
STAGE="$OUT/$NAME"
echo "== building Scarlet $VERSION"

# 1. frontend -> backend/pkm/static
if [[ "$SKIP_FE" == no ]]; then
  (cd "$REPO/frontend" && npm ci --no-audit --no-fund && npm run build)
fi
[[ -f "$REPO/frontend/dist/index.html" ]] || { echo "frontend/dist missing (run without --skip-frontend)" >&2; exit 1; }
rm -rf "$REPO/backend/pkm/static"
cp -r "$REPO/frontend/dist" "$REPO/backend/pkm/static"

# 2. application wheel + dependency wheels for the target platform
rm -rf "$STAGE" "$OUT/$NAME.tar.gz" "$OUT/$NAME.tar.gz.sha256"
mkdir -p "$STAGE/wheels"
"$PY" -m pip wheel --no-deps -q -w "$STAGE/wheels" "$REPO/backend"
WHEEL="$(ls "$STAGE"/wheels/pkm-*.whl)"
"$PY" -m pip download -q -d "$STAGE/wheels" --only-binary=:all: --implementation cp --python-version 3.12 \
  --abi cp312 --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
  --platform linux_x86_64 "$WHEEL" pip uvloop
# pip evaluates environment markers for the BUILD host: Linux-only dependencies (uvloop for
# uvicorn[standard]) are listed explicitly above. Fail if the set is not installable on the target.
for req in uvloop httptools websockets watchfiles argon2_cffi_bindings pyyaml; do
  ls "$STAGE/wheels" | grep -qi "^${req}-" || { echo "missing wheel for $req" >&2; exit 1; }
done
rm -rf "$REPO/backend/pkm/static"

# 3. scripts, deployment files, configuration templates, documentation
cp -r "$REPO/scripts" "$STAGE/scripts"
rm -f "$STAGE/scripts/build-release.sh"
for s in install.sh uninstall.sh upgrade.sh backup.sh restore.sh; do
  cp "$REPO/scripts/$s" "$STAGE/$s"
done
cp -r "$REPO/deploy" "$STAGE/deploy"
mkdir -p "$STAGE/config"
cp "$REPO/config/config.example.yaml" "$STAGE/config/"
cp "$REPO/.env.example" "$STAGE/.env.example"
cp -r "$REPO/docs" "$STAGE/docs"
for f in README.md ARCHITECTURE.md INSTALL.md OPERATIONS.md SECURITY.md TROUBLESHOOTING.md DEVELOPMENT.md BACKUP.md CHANGELOG.md; do
  [[ -f "$REPO/$f" ]] && cp "$REPO/$f" "$STAGE/"
done
echo "$VERSION" > "$STAGE/VERSION"
# Scripts, systemd units and configuration must have LF line endings on the target (builds on Windows!).
find "$STAGE" -maxdepth 1 -name '*.sh' -print0 | xargs -0 sed -i 's/\r$//'
find "$STAGE/scripts" "$STAGE/deploy" "$STAGE/config" -type f -print0 | xargs -0 sed -i 's/\r$//'
sed -i 's/\r$//' "$STAGE/.env.example"
chmod 0755 "$STAGE"/*.sh "$STAGE"/scripts/*.sh "$STAGE"/scripts/lib/*.sh

# 4. archive + checksum (LF line endings and executable bits are preserved by tar)
(cd "$OUT" && tar --owner=0 --group=0 -czf "$NAME.tar.gz" "$NAME" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "== release ready:"
ls -lh "$OUT/$NAME.tar.gz" "$OUT/$NAME.tar.gz.sha256"
echo "   wheels: $(ls "$STAGE/wheels" | wc -l)"
