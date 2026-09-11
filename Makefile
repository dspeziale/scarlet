.PHONY: help venv install dev up down logs test test-unit test-e2e lint format typecheck migrate migration seed run worker beat shell build package clean

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
FLASK ?= .venv/bin/flask
COMPOSE ?= docker compose

help:
	@echo "SCARLET developer targets:"
	@echo "  make venv install   create venv and install dev dependencies"
	@echo "  make dev            start postgres, redis, web, worker, beat, nginx, mock host (compose)"
	@echo "  make down           stop the development stack"
	@echo "  make migrate        apply database migrations"
	@echo "  make migration m=.. create a new migration"
	@echo "  make seed           seed environments/RBAC/admin (+demo data)"
	@echo "  make run            run the Flask dev server locally (SQLite)"
	@echo "  make worker         run a Celery worker locally"
	@echo "  make test           run the test-suite"
	@echo "  make lint format    ruff / black"
	@echo "  make package        build the example packages into dist/"

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements/dev.txt

dev up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

migrate:
	FLASK_APP=wsgi.py $(FLASK) db upgrade

migration:
	FLASK_APP=wsgi.py $(FLASK) db migrate -m "$(m)"

seed:
	FLASK_APP=wsgi.py $(FLASK) scarlet seed --with-demo

run:
	FLASK_APP=wsgi.py SCARLET_ENV=development $(FLASK) run --debug --port 5000

worker:
	.venv/bin/celery -A celery_worker.celery worker --loglevel=INFO -Q scarlet,scarlet-deploy,scarlet-maintenance

beat:
	.venv/bin/celery -A celery_worker.celery beat --loglevel=INFO

shell:
	FLASK_APP=wsgi.py $(FLASK) shell

test:
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit -q

test-e2e:
	$(PY) -m pytest tests/e2e tests/integration -q

lint:
	.venv/bin/ruff check app tests scripts
	.venv/bin/black --check app tests scripts

format:
	.venv/bin/ruff check --fix app tests scripts
	.venv/bin/black app tests scripts

typecheck:
	.venv/bin/mypy app

build:
	docker build -f docker/Dockerfile -t scarlet:latest .

package:
	$(PY) scripts/build-scarlet-package.py --source examples/podman-app --version 1.0.0 --output dist/
	$(PY) scripts/build-scarlet-package.py --source examples/docker-app --version 1.0.0 --output dist/
	$(PY) scripts/build-scarlet-package.py --source examples/kubernetes-app --version 1.0.0 --output dist/

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
