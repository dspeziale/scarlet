"""Celery worker entry point: ``celery -A celery_worker.celery worker``."""

from app import create_app
from app.tasks.celery_app import celery

flask_app = create_app()

__all__ = ["celery", "flask_app"]
