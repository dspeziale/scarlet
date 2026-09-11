# syntax=docker/dockerfile:1.6
# SCARLET application image (web + worker + beat share the same image).
# Builds with Docker or Podman:  podman build -f docker/Dockerfile -t scarlet:latest .

# ---------- build stage: compile wheels --------------------------------------------------
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements/base.txt requirements/base.txt
RUN pip wheel --wheel-dir /wheels -r requirements/base.txt

# ---------- runtime stage ----------------------------------------------------------------------
FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="SCARLET" \
      org.opencontainers.image.description="System Container Application Release, Lifecycle & Environment Tool" \
      org.opencontainers.image.source="https://example.internal/scarlet"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SCARLET_ARTIFACT_PATH=/data/scarlet/artifacts \
    SCARLET_UPLOAD_TMP_PATH=/data/scarlet/uploads \
    SCARLET_LOG_PATH=/data/scarlet/logs \
    FLASK_APP=wsgi.py
RUN apt-get update && apt-get install -y --no-install-recommends curl tini openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 scarlet && useradd --uid 10001 --gid scarlet --home /app --shell /usr/sbin/nologin scarlet \
    && mkdir -p /data/scarlet/artifacts /data/scarlet/uploads /data/scarlet/logs && chown -R scarlet:scarlet /data/scarlet
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels
COPY --chown=scarlet:scarlet app ./app
COPY --chown=scarlet:scarlet migrations ./migrations
COPY --chown=scarlet:scarlet config ./config
COPY --chown=scarlet:scarlet scripts ./scripts
COPY --chown=scarlet:scarlet wsgi.py celery_worker.py pyproject.toml ./
COPY --chown=scarlet:scarlet docker/entrypoint.sh /usr/local/bin/scarlet-entrypoint
RUN chmod +x /usr/local/bin/scarlet-entrypoint scripts/*.py 2>/dev/null || true
USER scarlet
VOLUME ["/data/scarlet"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/scarlet-entrypoint"]
CMD ["web"]
