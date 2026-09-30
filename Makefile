# Comandi per lo sviluppatore. Sul server NON si usa make: si usa appctl.
#
#   make install     crea il venv e installa le dipendenze di sviluppo
#   make lint        ruff (lint + formato)
#   make test        unit test (app + appctl)
#   make audit       pip-audit sulle dipendenze runtime
#   make build       costruisce l'immagine locale scarlet:local
#   make run         avvia app + db in locale con Docker Compose (http://127.0.0.1:8080)
#   make stop        ferma l'ambiente locale
#   make logs        log dell'ambiente locale
#   make integration test di integrazione appctl con Docker reale (solo Linux)

PY ?= python3
VENV ?= .venv
ifeq ($(OS),Windows_NT)
  BIN := $(VENV)/Scripts
else
  BIN := $(VENV)/bin
endif

IMAGE ?= scarlet:local
APP_NAME ?= scarlet
LOCAL_DIR := .local
COMMIT := $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)
VERSION := $(shell cat VERSION)
COMPOSE := docker compose -f deploy/compose.yaml -f deploy/compose.db.yaml -f deploy/compose.local.yaml
COMPOSE_ENV := IMAGE=$(IMAGE) APP_NAME=$(APP_NAME) APP_DIR=$(CURDIR)/$(LOCAL_DIR) APP_PORT=8080

.PHONY: install lint format test audit build run stop logs migrate integration clean

install:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -r requirements-dev.txt -e .

lint:
	$(BIN)/python -m ruff check .
	$(BIN)/python -m ruff format --check .

format:
	$(BIN)/python -m ruff format .
	$(BIN)/python -m ruff check --fix .

test:
	$(BIN)/python -m pytest tests platform/appctl/tests platform/tests/unit

audit:
	$(BIN)/python -m pip_audit -r requirements.txt --strict

build:
	docker build \
	  --build-arg APP_VERSION=$(VERSION) \
	  --build-arg APP_COMMIT=$(COMMIT) \
	  --build-arg APP_BUILD_TIME=$(shell date -u +%Y-%m-%dT%H:%M:%SZ) \
	  -t $(IMAGE) .

$(LOCAL_DIR)/secrets/app.secrets.env:
	mkdir -p $(LOCAL_DIR)/config $(LOCAL_DIR)/secrets $(LOCAL_DIR)/data/postgres
	cp deploy/env/development.env $(LOCAL_DIR)/config/app.env
	sed 's/CHANGE_ME/localdev/g' deploy/secrets.env.example > $(LOCAL_DIR)/secrets/app.secrets.env

run: build $(LOCAL_DIR)/secrets/app.secrets.env
	$(COMPOSE_ENV) $(COMPOSE) up -d db
	$(COMPOSE_ENV) $(COMPOSE) run --rm --no-deps app alembic upgrade head
	$(COMPOSE_ENV) $(COMPOSE) up -d
	@echo "Scarlet in esecuzione: http://127.0.0.1:8080  (health: /health, ready: /ready)"

migrate: $(LOCAL_DIR)/secrets/app.secrets.env
	$(COMPOSE_ENV) $(COMPOSE) run --rm app alembic upgrade head

stop:
	-$(COMPOSE_ENV) $(COMPOSE) down

logs:
	$(COMPOSE_ENV) $(COMPOSE) logs -f --tail 200

integration:
	APPCTL_INTEGRATION=1 $(BIN)/python -m pytest platform/tests/integration -m integration -v

clean: stop
	rm -rf $(LOCAL_DIR) .pytest_cache .ruff_cache dist build
