"""
One-off schema upgrade: add network-discovery columns to the `probes` table.

Needed because the deployment creates schema with db.create_all() (which only
creates missing tables, never new columns on existing ones). Run this once
against the production database after deploying the network-discovery feature.

Usage:
    python migrate_probe_network.py        # uses DATABASE_URL from env / .env

Idempotent: skips columns that already exist. Works on PostgreSQL and SQLite.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db

# column_name -> SQL type fragment (dialect-portable)
NEW_COLUMNS = {
    "interfaces": "JSON",
    "subnets": "JSON",
    "ids_interface": "VARCHAR(64)",
    "network_updated_at": "TIMESTAMP",
    "location": "VARCHAR(255)",
    "contact": "VARCHAR(255)",
    "notes": "TEXT",
}


def migrate() -> None:
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        if "probes" not in inspector.get_table_names():
            # Fresh database — create_all will build the table with all columns.
            db.create_all()
            print("probes table did not exist — created full schema.")
            return

        existing = {c["name"] for c in inspector.get_columns("probes")}
        added = []
        with db.engine.begin() as conn:
            for name, sql_type in NEW_COLUMNS.items():
                if name in existing:
                    print(f"  skip  {name} (already present)")
                    continue
                conn.execute(text(f"ALTER TABLE probes ADD COLUMN {name} {sql_type}"))
                added.append(name)
                print(f"  added {name} {sql_type}")

        print("Migration complete." if added else "Nothing to do — schema already up to date.")


if __name__ == "__main__":
    migrate()
