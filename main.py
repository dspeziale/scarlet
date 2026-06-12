import os
from flask import Flask
from app.core.config import Config
from app.core.db import db
from app.api.probes import bp as probes_bp
from app.views.admin import bp as admin_bp

def ensure_schema():
    """Idempotent, self-healing schema migration for all incremental columns/tables.
    Runs once per serverless cold start; every statement is guarded independently so a
    fresh deploy heals its database without manual migrations."""
    from sqlalchemy import text
    statements = [
        # users: username -> email
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
        "UPDATE users SET email = username WHERE email IS NULL",
        "ALTER TABLE users ALTER COLUMN username DROP NOT NULL",
        # probes: runtime info reported by the probe
        "ALTER TABLE probes ADD COLUMN IF NOT EXISTS runtime_info JSONB",
        # tasks -> command bus
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS params JSONB",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS issued_by VARCHAR",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE tasks ALTER COLUMN target_ip DROP NOT NULL",
        # devices: vulnerability blob
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS vulnerabilities JSONB",
        # suricata events
        """CREATE TABLE IF NOT EXISTS suricata_events (
            id UUID PRIMARY KEY, probe_id UUID NOT NULL, tenant_id UUID,
            event_ts VARCHAR, event_type VARCHAR, severity INTEGER, signature VARCHAR, signature_id VARCHAR,
            category VARCHAR, src_ip VARCHAR, dest_ip VARCHAR, proto VARCHAR,
            line VARCHAR, raw JSONB, received_at TIMESTAMP WITH TIME ZONE)""",
        "ALTER TABLE suricata_events ADD COLUMN IF NOT EXISTS event_type VARCHAR",
        # central IDS ruleset
        """CREATE TABLE IF NOT EXISTS ids_ruleset (
            id UUID PRIMARY KEY, source_url VARCHAR, version VARCHAR,
            rule_count INTEGER, rules_text TEXT, updated_at TIMESTAMP WITH TIME ZONE)""",
        "ALTER TABLE ids_ruleset ADD COLUMN IF NOT EXISTS categories JSONB",
        # wireless discovery (WiFi access points + BLE devices)
        """CREATE TABLE IF NOT EXISTS wifi_networks (
            id UUID PRIMARY KEY, tenant_id UUID, probe_id UUID NOT NULL,
            bssid VARCHAR NOT NULL, ssid VARCHAR, channel INTEGER, signal DOUBLE PRECISION, encryption VARCHAR,
            first_seen TIMESTAMP WITH TIME ZONE, last_seen TIMESTAMP WITH TIME ZONE)""",
        "ALTER TABLE wifi_networks ADD COLUMN IF NOT EXISTS band VARCHAR",
        """CREATE TABLE IF NOT EXISTS ble_devices (
            id UUID PRIMARY KEY, tenant_id UUID, probe_id UUID NOT NULL,
            address VARCHAR NOT NULL, name VARCHAR, rssi INTEGER,
            first_seen TIMESTAMP WITH TIME ZONE, last_seen TIMESTAMP WITH TIME ZONE)""",
        # audit log
        """CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY, ts TIMESTAMP WITH TIME ZONE, actor VARCHAR, role VARCHAR,
            action VARCHAR NOT NULL, detail TEXT, tenant_id UUID, ip VARCHAR)""",
        # per-tenant billing plans
        """CREATE TABLE IF NOT EXISTS tenant_billing (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL UNIQUE, currency VARCHAR DEFAULT 'EUR',
            fixed_fee DOUBLE PRECISION DEFAULT 0, price_per_probe DOUBLE PRECISION DEFAULT 0,
            price_per_asset DOUBLE PRECISION DEFAULT 0, price_per_scan DOUBLE PRECISION DEFAULT 0,
            price_per_alert DOUBLE PRECISION DEFAULT 0, price_per_ai DOUBLE PRECISION DEFAULT 0,
            updated_at TIMESTAMP WITH TIME ZONE)""",
        "ALTER TABLE tenant_billing ADD COLUMN IF NOT EXISTS price_per_gb DOUBLE PRECISION DEFAULT 0",
        "ALTER TABLE tenant_billing ADD COLUMN IF NOT EXISTS price_per_notification DOUBLE PRECISION DEFAULT 0",
        "ALTER TABLE tenant_billing ADD COLUMN IF NOT EXISTS price_per_cpu_min DOUBLE PRECISION DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS tenant_usage (
            id UUID PRIMARY KEY, tenant_id UUID NOT NULL UNIQUE,
            bytes_in DOUBLE PRECISION DEFAULT 0, notifications DOUBLE PRECISION DEFAULT 0,
            cpu_seconds DOUBLE PRECISION DEFAULT 0, updated_at TIMESTAMP WITH TIME ZONE)""",
    ]
    for stmt in statements:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()


def migrate_users_to_email():
    """Idempotent migration from the legacy username column to email-based login.
    Safe to call repeatedly; each step is guarded independently."""
    from sqlalchemy import text
    for stmt in (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(200)",
        "UPDATE users SET email = username WHERE email IS NULL",
        "ALTER TABLE users ALTER COLUMN username DROP NOT NULL",
    ):
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)

    from flask_login import LoginManager
    login_manager = LoginManager()
    login_manager.login_view = 'admin.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        try:
            return User.query.get(user_id)
        except Exception:
            # Self-healing lazy migration: username -> email schema
            db.session.rollback()
            migrate_users_to_email()
            try:
                return User.query.get(user_id)
            except Exception:
                db.session.rollback()
                return None

    # Self-heal the database schema once per cold start (before any query runs)
    _schema_state = {"ready": False}

    @app.before_request
    def _ensure_schema_once():
        if _schema_state["ready"]:
            return
        try:
            ensure_schema()
        except Exception:
            db.session.rollback()
        _schema_state["ready"] = True

    # Expose i18n helpers to every template
    @app.context_processor
    def inject_i18n():
        from app.i18n import translate, get_lang, LANGUAGES
        brand = os.environ.get("BRAND_NAME", "SCARLET")
        try:
            from app.models.settings import SystemSetting
            brand = SystemSetting.get_value("BRAND_NAME", brand) or brand
        except Exception:
            db.session.rollback()
        return {"t": translate, "lang": get_lang(), "languages": LANGUAGES, "brand": brand}

    # Register blueprints
    app.register_blueprint(probes_bp)
    app.register_blueprint(admin_bp)
    
    # We intentionally DO NOT call db.create_all() here.
    # Vercel imports this file during cold starts and build.
    # Connecting to the DB during import causes crashes if the connection times out.
    
    from app.views.site import bp as site_bp
    app.register_blueprint(site_bp)

    return app

# The app instance for Vercel WSGI
app = create_app()

@app.cli.command("init-db")
def init_db():
    import app.models.tenant
    import app.models.probe
    import app.models.device
    import app.models.user
    db.create_all()
    print("Database tables created.")

import click
@app.cli.command("create-superadmin")
@click.argument("email")
@click.argument("password")
def create_superadmin(email, password):
    from app.models.user import User

    email = email.strip().lower()
    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f"User {email} already exists.")
        return

    user = User(email=email, role='superadmin')
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print(f"Superadmin {email} created successfully!")

@app.route('/init-db-temp')
def init_db_route():
    try:
        import app.models.tenant
        import app.models.probe
        import app.models.device
        import app.models.user
        import app.models.suricata
        import app.models.ids
        import app.models.billing
        import app.models.wireless
        import app.models.audit
        from sqlalchemy import text
        
        # Create new tables
        db.create_all()
        
        # Manually alter existing tables since create_all doesn't do it
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE probes ADD COLUMN IF NOT EXISTS tenant_id UUID;"))
            conn.execute(text("ALTER TABLE probes ADD COLUMN IF NOT EXISTS license_code_id UUID;"))
            conn.commit()
            
        return "Tabelle del database create e migrate con successo su NeonDB!"
    except Exception as e:
        import traceback
        return f"<pre>Errore durante la migrazione: {traceback.format_exc()}</pre>", 500


if __name__ == '__main__':
    # Local development server
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
