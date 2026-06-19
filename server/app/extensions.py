"""Shared extension singletons — imported here to avoid circular imports."""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
