"""
Database seed script — creates system roles, permissions, and the SuperAdmin user.

Usage:
    flask --app app shell < seed.py
  or:
    python seed.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.extensions import db
from app.auth.password import hash_password
from app.models.user import User, Role, Permission

ROLES = [
    {
        "name": "SuperAdmin",
        "description": "Full platform access",
        "permissions": [
            ("tenants", "create"), ("tenants", "read"), ("tenants", "update"), ("tenants", "delete"),
            ("users", "create"), ("users", "read"), ("users", "update"), ("users", "delete"),
            ("probes", "create"), ("probes", "read"), ("probes", "update"), ("probes", "delete"),
            ("tasks", "create"), ("tasks", "read"), ("tasks", "update"), ("tasks", "delete"),
            ("telemetry", "read"), ("audit", "read"), ("accounting", "read"),
            ("probe_tokens", "create"), ("probe_tokens", "read"),
            ("keys", "rotate"),
        ],
    },
    {
        "name": "TenantAdmin",
        "description": "Manages own tenant resources",
        "permissions": [
            ("users", "create"), ("users", "read"), ("users", "update"),
            ("probes", "read"), ("probes", "update"),
            ("tasks", "create"), ("tasks", "read"), ("tasks", "update"), ("tasks", "delete"),
            ("telemetry", "read"), ("audit", "read"), ("accounting", "read"),
            ("probe_tokens", "create"), ("probe_tokens", "read"),
            ("keys", "rotate"),
        ],
    },
    {
        "name": "Operator",
        "description": "Runs authorised tasks and reads data",
        "permissions": [
            ("probes", "read"),
            ("tasks", "create"), ("tasks", "read"), ("tasks", "update"),
            ("telemetry", "read"), ("accounting", "read"),
        ],
    },
    {
        "name": "ReadOnly",
        "description": "Read-only access",
        "permissions": [
            ("probes", "read"), ("tasks", "read"), ("telemetry", "read"),
            ("audit", "read"), ("accounting", "read"),
        ],
    },
]

SUPERADMIN_EMAIL = os.environ.get("SUPERADMIN_EMAIL", "admin@soc-seattle.local")
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD", "ChangeMe!2025")
SUPERADMIN_USERNAME = os.environ.get("SUPERADMIN_USERNAME", "superadmin")


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # ── Permissions ──────────────────────────────────────────────────────
        perm_map: dict[tuple, Permission] = {}
        for role_def in ROLES:
            for resource, action in role_def["permissions"]:
                key = (resource, action)
                if key not in perm_map:
                    existing = db.session.query(Permission).filter_by(
                        resource=resource, action=action
                    ).first()
                    if not existing:
                        perm = Permission(
                            name=f"{resource}:{action}",
                            resource=resource,
                            action=action,
                        )
                        db.session.add(perm)
                        db.session.flush()
                        perm_map[key] = perm
                    else:
                        perm_map[key] = existing

        # ── Roles ─────────────────────────────────────────────────────────────
        for role_def in ROLES:
            existing = db.session.query(Role).filter_by(name=role_def["name"]).first()
            if not existing:
                role = Role(
                    name=role_def["name"],
                    description=role_def["description"],
                    is_system=True,
                )
                for key in role_def["permissions"]:
                    role.permissions.append(perm_map[key])
                db.session.add(role)
                print(f"  Created role: {role_def['name']}")
            else:
                print(f"  Role exists: {role_def['name']}")

        db.session.flush()

        # ── SuperAdmin user ────────────────────────────────────────────────────
        existing_sa = db.session.query(User).filter_by(email=SUPERADMIN_EMAIL).first()
        if not existing_sa:
            sa_role = db.session.query(Role).filter_by(name="SuperAdmin").first()
            sa = User(
                email=SUPERADMIN_EMAIL,
                username=SUPERADMIN_USERNAME,
                password_hash=hash_password(SUPERADMIN_PASSWORD),
                first_name="Super",
                last_name="Admin",
                is_superadmin=True,
                is_active=True,
            )
            if sa_role:
                sa.roles.append(sa_role)
            db.session.add(sa)
            print(f"  Created SuperAdmin: {SUPERADMIN_EMAIL}")
        else:
            print(f"  SuperAdmin exists: {SUPERADMIN_EMAIL}")

        db.session.commit()
        print("Seed complete.")


if __name__ == "__main__":
    seed()
