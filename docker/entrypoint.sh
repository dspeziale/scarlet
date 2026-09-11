#!/bin/sh
# SCARLET container entrypoint.
#   web     -> run migrations (unless SCARLET_SKIP_MIGRATIONS=true), seed RBAC/admin, start gunicorn
#   worker  -> celery worker
#   beat    -> celery beat (periodic reconciliation / cleanup / health sweep)
#   shell   -> flask shell
#   <cmd>   -> exec arbitrary command (e.g. flask scarlet seed --with-demo)
set -eu

ROLE="${1:-web}"
[ $# -gt 0 ] && shift

wait_for_db() {
    echo "[entrypoint] waiting for database..."
    i=0
    until python - <<'PY' 2>/dev/null
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
try:
    create_engine(url, pool_pre_ping=True).connect().execute(text("SELECT 1"))
except Exception as exc:
    sys.exit(1)
PY
    do
        i=$((i+1))
        [ "$i" -ge 60 ] && { echo "[entrypoint] database not reachable after 60 attempts"; exit 1; }
        sleep 2
    done
}

case "$ROLE" in
  web)
    wait_for_db
    if [ "${SCARLET_SKIP_MIGRATIONS:-false}" != "true" ]; then
        echo "[entrypoint] applying database migrations"
        flask db upgrade
        echo "[entrypoint] synchronizing roles and initial admin"
        flask scarlet seed
    fi
    echo "[entrypoint] starting gunicorn"
    exec gunicorn -c config/gunicorn.conf.py wsgi:app
    ;;
  worker)
    wait_for_db
    exec celery -A celery_worker.celery worker --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
        --concurrency="${CELERY_CONCURRENCY:-4}" -Q "${CELERY_QUEUES:-scarlet,scarlet-deploy,scarlet-maintenance}" \
        --max-tasks-per-child=200 "$@"
    ;;
  beat)
    wait_for_db
    exec celery -A celery_worker.celery beat --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
        --schedule=/tmp/celerybeat-schedule "$@"
    ;;
  shell)
    exec flask shell
    ;;
  *)
    exec "$ROLE" "$@"
    ;;
esac
