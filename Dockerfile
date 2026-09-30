# syntax=docker/dockerfile:1.7
#
# Immagine di Scarlet. Principi:
#  - multi-stage: le dipendenze vengono installate in uno stage separato, l'immagine finale
#    non contiene pip cache, compilatori o sorgenti superflui;
#  - base Debian slim (glibc): wheel binari di psycopg disponibili, debug piu' semplice di
#    distroless per un team che inizia con Docker; Alpine scartata (musl, wheel non sempre
#    disponibili);
#  - utente non-root con uid fisso (10001) usato anche dal compose;
#  - nessun secret: la configurazione arriva solo da variabili d'ambiente a runtime;
#  - il bundle di deploy (compose) viaggia dentro l'immagine in /deploy (vedi docs/ARCHITECTURE.md).
#
# Aggiornamenti dell'immagine base: Dependabot (ecosystem "docker") apre PR sul tag.
# RECOMMENDED: bloccare anche il digest (FROM python:3.12-slim-bookworm@sha256:...).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ----------------------------------------------------------------------------- builder
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Prima solo le dipendenze: il layer viene riusato dalla cache finche' requirements.txt non cambia.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Poi il pacchetto applicativo.
COPY pyproject.toml VERSION README.md ./
COPY src ./src
RUN pip install --no-deps . \
    && pip uninstall -y pip setuptools wheel

# ----------------------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Patch di sicurezza del sistema base + utente non privilegiato (uid/gid fissi).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root migrations ./migrations
# Bundle di deploy: estratto sul server da appctl (docker cp <container>:/deploy ...).
COPY --chown=root:root deploy /deploy

# I metadati di build stanno DOPO i layer pesanti: cambiano a ogni commit senza invalidare la cache.
ARG APP_VERSION=0.0.0-dev
ARG APP_COMMIT=unknown
ARG APP_BUILD_TIME=unknown
ENV APP_VERSION=${APP_VERSION} \
    APP_COMMIT=${APP_COMMIT} \
    APP_BUILD_TIME=${APP_BUILD_TIME}
LABEL org.opencontainers.image.title="scarlet" \
      org.opencontainers.image.description="Scarlet - inventario dei rilasci" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_COMMIT}" \
      org.opencontainers.image.created="${APP_BUILD_TIME}" \
      org.opencontainers.image.source="https://github.com/dspeziale/scarlet" \
      org.opencontainers.image.vendor="ISED"

USER 10001:10001

EXPOSE 8000

# Liveness a livello Docker; il deploy verifica anche /ready (docs/ARCHITECTURE.md §7).
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

ENTRYPOINT ["python", "-m", "scarlet"]
