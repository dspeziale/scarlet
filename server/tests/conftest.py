"""Pytest fixtures — SQLite in-memory, seeded roles + users."""

import os
import pytest

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")


@pytest.fixture(scope="session")
def app():
    from app import create_app
    application = create_app("testing")
    return application


@pytest.fixture(scope="session")
def db(app):
    from app.extensions import db as _db
    with app.app_context():
        _db.create_all()
        _seed_db(_db)
        yield _db
        _db.drop_all()


def _seed_db(db):
    from app.models.user import User, Role, Permission
    from app.auth.password import hash_password

    # Roles
    for rname in ["SuperAdmin", "TenantAdmin", "Operator", "ReadOnly"]:
        if not db.session.query(Role).filter_by(name=rname).first():
            r = Role(name=rname, description=rname, is_system=True)
            db.session.add(r)
    db.session.flush()

    # Superadmin
    if not db.session.query(User).filter_by(email="admin@test.local").first():
        sa_role = db.session.query(Role).filter_by(name="SuperAdmin").first()
        sa = User(
            email="admin@test.local",
            username="admin",
            password_hash=hash_password("Admin123!"),
            is_superadmin=True,
            is_active=True,
        )
        if sa_role:
            sa.roles.append(sa_role)
        db.session.add(sa)

    db.session.commit()


@pytest.fixture(scope="function")
def client(app, db):
    with app.test_client() as c:
        with app.app_context():
            yield c


@pytest.fixture(scope="function")
def auth_headers(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "Admin123!"},
    )
    token = resp.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def tenant(app, db, auth_headers, client):
    """Create and return a test tenant."""
    resp = client.post(
        "/api/v1/tenants",
        json={"name": "Test Corp", "plan": "basic"},
        headers=auth_headers,
    )
    return resp.get_json()


@pytest.fixture(scope="function")
def tenant_user(app, db, auth_headers, client, tenant):
    """Create a TenantAdmin user inside the test tenant."""
    resp = client.post(
        "/api/v1/users",
        json={
            "email": "tenant_admin@test.local",
            "username": "tadmin",
            "password": "Tadmin123!",
            "tenant_id": tenant["id"],
            "roles": ["TenantAdmin"],
        },
        headers=auth_headers,
    )
    return resp.get_json()


@pytest.fixture(scope="function")
def tenant_auth_headers(client, tenant_user):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "tenant_admin@test.local", "password": "Tadmin123!"},
    )
    token = resp.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
