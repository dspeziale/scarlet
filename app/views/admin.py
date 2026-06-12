from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models.probe import Probe
from app.models.tenant import Tenant, LicenseCode
from app.models.device import Device
from app.models.user import User
from app.core.db import db

bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='../templates')


_NO_TENANT = '00000000-0000-0000-0000-000000000000'


def _scope_tenant_id():
    """Returns the tenant id to scope queries to.
    None => all tenants (superadmin with no selection). A uuid string => that tenant."""
    if current_user.role == 'superadmin':
        return session.get('active_tenant_id')  # None => all tenants
    return str(current_user.tenant_id) if current_user.tenant_id else _NO_TENANT


@bp.app_context_processor
def inject_tenant_context():
    """Makes the active tenant + selectable tenant list available to every template."""
    try:
        if not current_user.is_authenticated:
            return {}
    except Exception:
        return {}
    from app.models.tenant import Tenant
    ctx = {"nav_tenants": [], "active_tenant": None}
    try:
        if current_user.role == 'superadmin':
            ctx["nav_tenants"] = Tenant.query.order_by(Tenant.name).all()
            tid = session.get('active_tenant_id')
            if tid:
                ctx["active_tenant"] = db.session.get(Tenant, __import__('uuid').UUID(tid)) if tid else None
        elif current_user.tenant_id:
            ctx["active_tenant"] = db.session.get(Tenant, current_user.tenant_id)
    except Exception:
        db.session.rollback()
    return ctx


@bp.route('/set-tenant', methods=['POST'])
@login_required
def set_tenant():
    if current_user.role == 'superadmin':
        tid = (request.form.get('tenant_id') or '').strip()
        if tid:
            session['active_tenant_id'] = tid
        else:
            session.pop('active_tenant_id', None)
    return redirect(request.referrer or url_for('admin.dashboard'))


def _audit(action, detail='', tenant_id=None):
    """Records a significant action in the audit log (best-effort)."""
    from app.models.audit import AuditLog
    try:
        db.session.add(AuditLog(
            actor=getattr(current_user, 'email', None),
            role=getattr(current_user, 'role', None),
            action=action,
            detail=str(detail)[:1000],
            tenant_id=tenant_id,
            ip=(request.headers.get('X-Forwarded-For') or request.remote_addr),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


@bp.route('/audit')
@login_required
def audit_log():
    if current_user.role != 'superadmin':
        return "Unauthorized", 403
    from app.models.audit import AuditLog
    try:
        logs = AuditLog.query.order_by(AuditLog.ts.desc()).limit(400).all()
    except Exception:
        db.session.rollback()
        logs = []
    return render_template('admin/audit.html', logs=logs)

def _ensure_user_email_column():
    """Lazy migration: move from username-based to email-based login."""
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


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    _ensure_user_email_column()

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            _audit('auth.login', email)
            return redirect(url_for('admin.dashboard'))

        flash('Invalid email or password', 'error')

    return render_template('admin/login.html')

@bp.route('/debug-schema')
def debug_schema():
    from app.core.db import db
    from sqlalchemy import text
    try:
        result = db.session.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'devices';"))
        cols = [{"column": r[0], "type": r[1]} for r in result]
        return {"columns": cols}
    except Exception as e:
        return f"Error: {str(e)}"

@bp.route('/alter-db-temp')
def alter_db_temp():
    from app.core.db import db
    from sqlalchemy import text
    try:
        db.session.execute(text("ALTER TABLE devices ADD COLUMN vulnerabilities JSONB;"))
        db.session.commit()
        return "Column added successfully"
    except Exception as e:
        db.session.rollback()
        return f"Error: {str(e)}"

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


@bp.route('/guide')
@login_required
def guide():
    """Complete platform usage guide."""
    return render_template('admin/guide.html')


@bp.route('/lang/<code>')
def set_language(code):
    """Switches the UI language (it/en) and returns to the previous page."""
    from app.i18n import LANGUAGES
    if code in LANGUAGES:
        session['lang'] = code
    return redirect(request.referrer or url_for('admin.dashboard'))

@bp.route('/tenants')
@login_required
def tenants():
    from sqlalchemy import text
    try:
        db.session.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS vulnerabilities JSONB;"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    if current_user.role == 'superadmin':
        tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
        probes = Probe.query.order_by(Probe.created_at.desc()).all()
        devices = Device.query.order_by(Device.last_seen.desc()).all()
    else:
        # Tenant admin sees only their tenant's data
        tenants = Tenant.query.filter_by(id=current_user.tenant_id).all()
        probes = Probe.query.filter_by(tenant_id=current_user.tenant_id).order_by(Probe.created_at.desc()).all()
        devices = Device.query.join(Probe).filter(Probe.tenant_id == current_user.tenant_id).order_by(Device.last_seen.desc()).all()
        
    return render_template('admin/dashboard.html', tenants=tenants, probes=probes, devices=devices)


def _is_online(probe, minutes=10):
    """A probe is considered online if its last_seen is within the given window."""
    from datetime import datetime, timezone, timedelta
    if not probe.last_seen:
        return False
    return (datetime.now(timezone.utc) - probe.last_seen) <= timedelta(minutes=minutes)


@bp.route('/probes')
@login_required
def probes_fleet():
    """Fleet view: every probe with status, reachability and asset counts."""
    scope = _scope_tenant_id()
    q = Probe.query
    if scope:
        q = q.filter(Probe.tenant_id == scope)
    probes = q.order_by(Probe.last_seen.desc().nullslast()).all()

    fleet = []
    online = 0
    for p in probes:
        is_on = _is_online(p)
        if is_on:
            online += 1
        fleet.append({
            "probe": p,
            "online": is_on,
            "device_count": len(p.devices) if hasattr(p, 'devices') else 0
        })

    summary = {
        "total": len(probes),
        "online": online,
        "offline": len(probes) - online,
    }
    return render_template('admin/probes.html', fleet=fleet, summary=summary)


@bp.route('/assets')
@login_required
def assets():
    """Network assets discovered across the fleet, with vulnerability tooling."""
    from sqlalchemy import text
    try:
        db.session.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS vulnerabilities JSONB;"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    scope = _scope_tenant_id()
    q = Device.query
    if scope:
        q = q.filter(Device.tenant_id == scope)
    devices = q.order_by(Device.last_seen.desc()).all()

    summary = {
        "total": len(devices),
        "vulnerable": sum(1 for d in devices if d.vulnerabilities),
        "services": sum(len(d.services) for d in devices if hasattr(d, 'services')),
    }
    return render_template('admin/assets.html', devices=devices, summary=summary)


@bp.route('/system')
@login_required
def system_status():
    """Server health & runtime information (superadmin only)."""
    if current_user.role != 'superadmin':
        return "Unauthorized", 403

    import sys
    import platform
    from datetime import datetime, timezone
    from sqlalchemy import text
    import flask
    import sqlalchemy as sa

    # Database connectivity probe
    db_ok = True
    db_error = None
    db_version = None
    try:
        row = db.session.execute(text("SELECT version();")).fetchone()
        db_version = row[0] if row else None
    except Exception as e:
        db_ok = False
        db_error = str(e)
        db.session.rollback()

    # Mask the DB host without leaking credentials
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_dialect = uri.split('://', 1)[0] if '://' in uri else 'unknown'
    db_host = 'unknown'
    if '@' in uri:
        try:
            db_host = uri.split('@', 1)[1].split('/', 1)[0]
        except Exception:
            pass

    counts = {}
    try:
        counts = {
            "tenants": Tenant.query.count(),
            "probes": Probe.query.count(),
            "devices": Device.query.count(),
            "users": User.query.count(),
        }
    except Exception:
        db.session.rollback()

    info = {
        "db_ok": db_ok,
        "db_error": db_error,
        "db_version": db_version,
        "db_dialect": db_dialect,
        "db_host": db_host,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "flask_version": getattr(flask, '__version__', 'n/a'),
        "sqlalchemy_version": sa.__version__,
        "server_time": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        "debug": current_app.debug,
        "counts": counts,
    }
    return render_template('admin/system.html', info=info)


def _ensure_suricata_table():
    from sqlalchemy import text
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS suricata_events (
                id UUID PRIMARY KEY, probe_id UUID NOT NULL, tenant_id UUID,
                event_ts VARCHAR, event_type VARCHAR, severity INTEGER, signature VARCHAR, signature_id VARCHAR,
                category VARCHAR, src_ip VARCHAR, dest_ip VARCHAR, proto VARCHAR,
                line VARCHAR, raw JSONB, received_at TIMESTAMP WITH TIME ZONE
            )
        """))
        db.session.execute(text("ALTER TABLE suricata_events ADD COLUMN IF NOT EXISTS event_type VARCHAR;"))
        db.session.commit()
    except Exception:
        db.session.rollback()


@bp.route('/threats')
@login_required
def threats():
    """Threat Monitor: live Suricata IDS feed streamed from the fleet."""
    _ensure_suricata_table()
    return render_template('admin/threats.html')


@bp.route('/threats/feed')
@login_required
def threats_feed():
    """JSON feed of recent Suricata events, scoped to the user's tenant."""
    from app.models.suricata import SuricataEvent
    _ensure_suricata_table()

    try:
        q = SuricataEvent.query
        scope = _scope_tenant_id()
        if scope:
            q = q.filter(SuricataEvent.tenant_id == scope)
        events = q.order_by(SuricataEvent.received_at.desc()).limit(300).all()
    except Exception:
        db.session.rollback()
        events = []

    # Return oldest-first so the terminal reads naturally
    out = []
    for e in reversed(events):
        out.append({
            "id": str(e.id),
            "probe_id": str(e.probe_id),
            "event_type": e.event_type,
            "severity": e.severity,
            "severity_color": e.severity_color,
            "signature": e.signature,
            "src_ip": e.src_ip,
            "dest_ip": e.dest_ip,
            "proto": e.proto,
            "line": e.line,
            "received_at": e.received_at.strftime('%Y-%m-%d %H:%M:%S') if e.received_at else '',
        })
    return jsonify({"events": out})


@bp.route('/threat-intel')
@login_required
def threat_intel():
    """Threat Intelligence: aggregated analytics over collected Suricata events."""
    from app.models.suricata import SuricataEvent
    from collections import Counter
    from datetime import datetime, timezone, timedelta
    _ensure_suricata_table()

    try:
        q = SuricataEvent.query
        scope = _scope_tenant_id()
        if scope:
            q = q.filter(SuricataEvent.tenant_id == scope)
        # Analyse the most recent window of events
        events = q.order_by(SuricataEvent.received_at.desc()).limit(5000).all()
    except Exception:
        db.session.rollback()
        events = []

    alerts = [e for e in events if (e.event_type == 'alert' or e.severity is not None)]
    now = datetime.now(timezone.utc)
    last_hour = sum(1 for e in events if e.received_at and (now - e.received_at) <= timedelta(hours=1))

    top_sigs = Counter(e.signature for e in alerts if e.signature).most_common(10)
    top_sources = Counter(e.src_ip for e in alerts if e.src_ip).most_common(10)
    top_dests = Counter(e.dest_ip for e in alerts if e.dest_ip).most_common(10)
    proto_mix = Counter(e.proto for e in events if e.proto).most_common(6)
    sev_counts = Counter(e.severity for e in alerts if e.severity is not None)

    stats = {
        "total_events": len(events),
        "total_alerts": len(alerts),
        "events_last_hour": last_hour,
        "unique_signatures": len({e.signature for e in alerts if e.signature}),
        "unique_sources": len({e.src_ip for e in alerts if e.src_ip}),
        "high_severity": sum(1 for e in alerts if e.severity is not None and e.severity <= 1),
        "sev_high": sev_counts.get(1, 0),
        "sev_med": sev_counts.get(2, 0),
        "sev_low": sum(v for k, v in sev_counts.items() if k and k >= 3),
    }

    return render_template(
        'admin/threat_intel.html',
        stats=stats,
        top_sigs=top_sigs,
        top_sources=top_sources,
        top_dests=top_dests,
        proto_mix=proto_mix,
    )


@bp.route('/threat-intel/briefing', methods=['POST'])
@login_required
def threat_briefing():
    """Generates an AI threat briefing from recent Suricata alerts using Groq."""
    import json
    import requests
    from collections import Counter
    from app.models.suricata import SuricataEvent
    from app.models.settings import SystemSetting
    _ensure_suricata_table()

    try:
        q = SuricataEvent.query
        scope = _scope_tenant_id()
        if scope:
            q = q.filter(SuricataEvent.tenant_id == scope)
        events = q.order_by(SuricataEvent.received_at.desc()).limit(2000).all()
    except Exception:
        db.session.rollback()
        events = []

    alerts = [e for e in events if (e.event_type == 'alert' or e.severity is not None)]
    if not alerts:
        return jsonify({"error": "No IDS alerts collected yet. Start Suricata on a probe to gather data."}), 400

    api_key = SystemSetting.get_value('GROQ_API_KEY')
    model = SystemSetting.get_value('GROQ_MODEL', 'llama-3.3-70b-versatile')
    if not api_key:
        return jsonify({"error": "Groq API Key is not configured in Settings."}), 400

    top_sigs = Counter(e.signature for e in alerts if e.signature).most_common(15)
    top_sources = Counter(e.src_ip for e in alerts if e.src_ip).most_common(15)
    summary = {
        "total_alerts": len(alerts),
        "top_signatures": top_sigs,
        "top_source_ips": top_sources,
    }

    prompt = f"""You are a senior SOC analyst. Based on the following aggregated Suricata IDS
alert telemetry from a monitored network, produce a concise threat briefing.

<Telemetry>
{json.dumps(summary, indent=2)}
</Telemetry>

Provide, in Markdown:
1. **Threat Overview** — what is happening at a glance.
2. **Notable Threats** — interpret the top signatures and likely attack techniques (map to MITRE ATT&CK where possible).
3. **Suspicious Actors** — call out source IPs worth investigating.
4. **Recommended Actions** — prioritized, concrete next steps.
Be precise and do not invent data not present above."""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a professional SOC analyst. Output clean Markdown."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return jsonify({"error": f"Groq API Error: {resp.text}"}), resp.status_code
        analysis = resp.json()['choices'][0]['message']['content']
        return jsonify({"markdown": analysis}), 200
    except Exception as e:
        return jsonify({"error": f"Groq request failed: {str(e)}"}), 500


DEFAULT_RULES_URL = "https://rules.emergingthreats.net/open/suricata-7.0.3/emerging-all.rules"


def _ensure_ids_table():
    from sqlalchemy import text
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS ids_ruleset (
                id UUID PRIMARY KEY, source_url VARCHAR, version VARCHAR,
                rule_count INTEGER, rules_text TEXT, updated_at TIMESTAMP WITH TIME ZONE
            )
        """))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _parse_ruleset(raw_bytes, url):
    """Returns (rules_text, rule_count). Handles .tar.gz bundles and plain .rules."""
    import io, gzip, tarfile

    text = None
    # gzip magic
    is_gz = raw_bytes[:2] == b'\x1f\x8b' or url.endswith('.gz') or url.endswith('.tgz')
    if is_gz:
        try:
            # Try tarball first (ET Open ships emerging.rules.tar.gz)
            tf = tarfile.open(fileobj=io.BytesIO(raw_bytes), mode='r:gz')
            parts = []
            for m in tf.getmembers():
                if m.isfile() and m.name.endswith('.rules'):
                    f = tf.extractfile(m)
                    if f:
                        parts.append(f.read().decode('utf-8', 'ignore'))
            text = "\n".join(parts)
        except tarfile.ReadError:
            # Plain gzip (single file)
            text = gzip.decompress(raw_bytes).decode('utf-8', 'ignore')
    else:
        text = raw_bytes.decode('utf-8', 'ignore')

    actions = ('alert ', 'drop ', 'reject ', 'pass ', 'sdrop ')
    count = sum(1 for ln in text.splitlines()
                if ln.strip() and not ln.lstrip().startswith('#') and ln.lstrip().startswith(actions))
    return text, count


from app.services import ids_rules as _ids


@bp.route('/ids-rules', methods=['GET'])
@login_required
def ids_rules():
    if current_user.role != 'superadmin':
        return "Unauthorized", 403
    from app.models.ids import IdsRuleset
    _ensure_ids_table()
    rs = IdsRuleset.current()
    active_count = None
    if rs and rs.categories is not None:
        active_count = sum(c['count'] for c in rs.categories if c.get('enabled'))
    return render_template('admin/ids_rules.html', ruleset=rs, default_url=DEFAULT_RULES_URL,
                           templates=_ids.DETECTION_TEMPLATES, active_count=active_count)


@bp.route('/ids-rules/template', methods=['POST'])
@login_required
def ids_rules_template():
    """Applies a predefined detection template, toggling categories accordingly."""
    if current_user.role != 'superadmin':
        return jsonify({"error": "Unauthorized"}), 403
    from app.models.ids import IdsRuleset
    _ensure_ids_table()
    rs = IdsRuleset.current()
    if not rs or not rs.categories:
        return jsonify({"error": "No ruleset prepared yet."}), 400

    name = (request.form.get('template') or '').strip()
    new_cats = _ids.apply_template(rs.categories, name)
    if new_cats is None:
        return jsonify({"error": f"Unknown template: {name}"}), 400
    rs.categories = new_cats
    db.session.commit()
    active = sum(c['count'] for c in new_cats if c['enabled'])
    return jsonify({"ok": True, "active_rules": active,
                    "message": f"Applied '{name}': {active} rules active."}), 200


@bp.route('/ids-rules/push', methods=['POST'])
@login_required
def ids_rules_push():
    """Pushes the active ruleset to the fleet now by issuing suricata_reload_rules
    to every paired probe in scope (otherwise probes pick it up on next Suricata start)."""
    if current_user.role != 'superadmin':
        return jsonify({"error": "Unauthorized"}), 403
    scope = _scope_tenant_id()
    q = Probe.query.filter_by(status='paired')
    if scope:
        q = q.filter(Probe.tenant_id == scope)
    probes = q.all()
    n = 0
    for p in probes:
        _issue_command(p, 'suricata_reload_rules', {})
        n += 1
    _audit('ids.push', f"reload to {n} probes")
    return jsonify({"ok": True, "message": f"Rule update pushed to {n} paired probe(s). Probes running Suricata reload immediately; others apply on next start."}), 200


@bp.route('/ids-rules/update', methods=['POST'])
@login_required
def ids_rules_update():
    if current_user.role != 'superadmin':
        return jsonify({"error": "Unauthorized"}), 403
    import hashlib
    import requests
    from app.models.ids import IdsRuleset
    _ensure_ids_table()

    url = (request.form.get('source_url') or '').strip() or DEFAULT_RULES_URL
    try:
        resp = requests.get(url, timeout=90, stream=True)
        if resp.status_code != 200:
            return jsonify({"error": f"Download failed: HTTP {resp.status_code}"}), 400
        # Generous cap; accumulate efficiently with a bytearray
        max_bytes = 250 * 1024 * 1024
        buf = bytearray()
        for chunk in resp.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                return jsonify({"error": "Ruleset exceeds the 250MB cap."}), 400
        raw = bytes(buf)
    except Exception as e:
        return jsonify({"error": f"Download error: {str(e)}"}), 502

    try:
        rules_text, count = _parse_ruleset(raw, url)
    except Exception as e:
        return jsonify({"error": f"Failed to parse ruleset: {str(e)}"}), 400

    if count == 0:
        return jsonify({"error": "No valid Suricata rules found at that URL."}), 400

    version = hashlib.sha256(rules_text.encode('utf-8')).hexdigest()[:12]

    rs = IdsRuleset.current()
    prev_enabled = None
    if rs and rs.categories:
        prev_enabled = {c['name'] for c in rs.categories if c.get('enabled')}
    if not rs:
        rs = IdsRuleset()
        db.session.add(rs)
    rs.source_url = url
    rs.version = version
    rs.rule_count = count
    rs.rules_text = rules_text
    rs.categories = _ids.categorize(rules_text, prev_enabled)
    db.session.commit()

    return jsonify({"ok": True, "version": version, "rule_count": count,
                    "categories": len(rs.categories),
                    "message": f"Prepared {count} rules in {len(rs.categories)} categories (v{version})."}), 200


@bp.route('/ids-rules/categories', methods=['POST'])
@login_required
def ids_rules_categories():
    """Sets which rule categories are active and shipped to probes."""
    if current_user.role != 'superadmin':
        return jsonify({"error": "Unauthorized"}), 403
    from app.models.ids import IdsRuleset
    _ensure_ids_table()
    rs = IdsRuleset.current()
    if not rs or not rs.categories:
        return jsonify({"error": "No ruleset prepared yet."}), 400

    enabled = set(request.form.getlist('enabled')) or set((request.get_json(silent=True) or {}).get('enabled', []))
    cats = []
    active = 0
    for c in rs.categories:
        on = c['name'] in enabled
        cats.append({"name": c['name'], "count": c['count'], "enabled": on})
        if on:
            active += c['count']
    rs.categories = cats
    db.session.commit()
    return jsonify({"ok": True, "active_rules": active,
                    "message": f"{active} rules active across {sum(1 for c in cats if c['enabled'])} categories. Probes re-sync on next Suricata start."}), 200


# ===========================================================================
# Billing / accountability
# ===========================================================================
def _tenant_or_403(tenant_id):
    """Resolves a tenant the current user is allowed to see, else None."""
    from app.models.tenant import Tenant
    t = db.session.get(Tenant, __import__('uuid').UUID(str(tenant_id))) if tenant_id else None
    if not t:
        return None
    if current_user.role != 'superadmin' and str(current_user.tenant_id) != str(t.id):
        return None
    return t


def _compute_billing(tenant, plan):
    """Computes current-period usage and charges for a tenant given its plan."""
    from app.models.probe import Probe, Task
    from app.models.device import Device
    from app.models.suricata import SuricataEvent

    n_probes = Probe.query.filter_by(tenant_id=tenant.id).count()
    n_assets = Device.query.filter_by(tenant_id=tenant.id).count()
    try:
        n_scans = Task.query.join(Probe).filter(Probe.tenant_id == tenant.id, Task.action == 'vuln_scan').count()
    except Exception:
        db.session.rollback(); n_scans = 0
    try:
        n_alerts = SuricataEvent.query.filter_by(tenant_id=tenant.id).count()
    except Exception:
        db.session.rollback(); n_alerts = 0

    # Metered usage (bandwidth / notifications / CPU)
    from app.models.billing import TenantUsage
    gb = notifs = cpu_min = 0.0
    try:
        u = TenantUsage.query.filter_by(tenant_id=tenant.id).first()
        if u:
            gb = (u.bytes_in or 0) / 1e9
            notifs = u.notifications or 0
            cpu_min = (u.cpu_seconds or 0) / 60.0
    except Exception:
        db.session.rollback()

    cur = plan.currency if plan else 'EUR'
    fee = plan.fixed_fee if plan else 0.0
    pp = plan.price_per_probe if plan else 0.0
    pa = plan.price_per_asset if plan else 0.0
    ps = plan.price_per_scan if plan else 0.0
    pal = plan.price_per_alert if plan else 0.0
    pgb = getattr(plan, 'price_per_gb', 0.0) or 0.0 if plan else 0.0
    pn = getattr(plan, 'price_per_notification', 0.0) or 0.0 if plan else 0.0
    pcpu = getattr(plan, 'price_per_cpu_min', 0.0) or 0.0 if plan else 0.0

    lines = [
        {"label": "Fixed Fee", "detail": "recurring base", "amount_val": fee},
        {"label": "Probes", "detail": f"{n_probes} × {pp:.2f}", "amount_val": n_probes * pp},
        {"label": "Assets", "detail": f"{n_assets} × {pa:.2f}", "amount_val": n_assets * pa},
        {"label": "Vuln Scans", "detail": f"{n_scans} × {ps:.2f}", "amount_val": n_scans * ps},
        {"label": "IDS Alerts", "detail": f"{n_alerts} × {pal:.4f}", "amount_val": n_alerts * pal},
        {"label": "Bandwidth", "detail": f"{gb:.3f} GB × {pgb:.2f}", "amount_val": gb * pgb},
        {"label": "Notifications", "detail": f"{int(notifs)} × {pn:.2f}", "amount_val": notifs * pn},
        {"label": "CPU", "detail": f"{cpu_min:.1f} min × {pcpu:.4f}", "amount_val": cpu_min * pcpu},
    ]
    total = sum(l["amount_val"] for l in lines)
    for l in lines:
        l["amount"] = f"{cur} {l['amount_val']:.2f}"
    return {"currency": cur, "lines": lines, "total_val": total, "total": f"{cur} {total:.2f}",
            "usage": {"probes": n_probes, "assets": n_assets, "scans": n_scans, "alerts": n_alerts,
                      "gb": round(gb, 3), "notifications": int(notifs), "cpu_min": round(cpu_min, 1)}}


@bp.route('/billing')
@login_required
def billing():
    from app.models.tenant import Tenant
    from app.models.billing import TenantBilling

    if current_user.role == 'superadmin':
        scope = _scope_tenant_id()
        tenants = Tenant.query.filter_by(id=scope).all() if scope else Tenant.query.order_by(Tenant.name).all()
    else:
        tenants = Tenant.query.filter_by(id=current_user.tenant_id).all()

    rows = []
    for t in tenants:
        plan = TenantBilling.for_tenant(t.id)
        rows.append({"tenant": t, "plan": plan, "billing": _compute_billing(t, plan)})
    return render_template('admin/billing.html', rows=rows)


@bp.route('/billing/<tenant_id>/save', methods=['POST'])
@login_required
def billing_save(tenant_id):
    if current_user.role != 'superadmin':
        return "Unauthorized", 403
    from app.models.billing import TenantBilling
    t = _tenant_or_403(tenant_id)
    if not t:
        return "Not found", 404

    plan = TenantBilling.for_tenant(t.id)
    if not plan:
        plan = TenantBilling(tenant_id=t.id)
        db.session.add(plan)

    def f(name, default=0.0):
        try:
            return float(request.form.get(name, default) or 0)
        except ValueError:
            return default

    plan.currency = (request.form.get('currency') or 'EUR').strip()[:8]
    plan.fixed_fee = f('fixed_fee')
    plan.price_per_probe = f('price_per_probe')
    plan.price_per_asset = f('price_per_asset')
    plan.price_per_scan = f('price_per_scan')
    plan.price_per_alert = f('price_per_alert')
    plan.price_per_gb = f('price_per_gb')
    plan.price_per_notification = f('price_per_notification')
    plan.price_per_cpu_min = f('price_per_cpu_min')
    db.session.commit()
    _audit('billing.update', t.name, tenant_id=t.id)
    flash('Billing plan saved.', 'success')
    return redirect(url_for('admin.billing'))


# ===========================================================================
# PDF reports & notifications
# ===========================================================================
def _gather_report_data(tenant):
    from app.models.probe import Probe
    from app.models.device import Device
    from app.models.suricata import SuricataEvent
    from app.models.billing import TenantBilling

    probes = Probe.query.filter_by(tenant_id=tenant.id).all()
    devices = Device.query.filter_by(tenant_id=tenant.id).all()
    try:
        alerts = SuricataEvent.query.filter_by(tenant_id=tenant.id).order_by(SuricataEvent.received_at.desc()).limit(50).all()
    except Exception:
        db.session.rollback(); alerts = []
    plan = TenantBilling.for_tenant(tenant.id)
    billing = _compute_billing(tenant, plan)
    return probes, devices, alerts, billing


@bp.route('/report/<tenant_id>.pdf')
@login_required
def report_pdf(tenant_id):
    from app.services.reports import build_tenant_report
    from flask import Response
    t = _tenant_or_403(tenant_id)
    if not t:
        return "Not found", 404
    probes, devices, alerts, billing = _gather_report_data(t)
    from app.models.settings import SystemSetting
    brand = SystemSetting.get_value('BRAND_NAME', 'SCARLET')
    pdf = build_tenant_report(t, probes, devices, alerts, billing, brand=brand)
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename=scarlet-report-{t.name}.pdf'})


@bp.route('/report/<tenant_id>/email', methods=['POST'])
@login_required
def report_email(tenant_id):
    from app.services.reports import build_tenant_report
    from app.services.notify import send_email
    t = _tenant_or_403(tenant_id)
    if not t:
        return jsonify({"error": "Not found"}), 404
    to_addr = (request.form.get('to') or '').strip()
    if not to_addr:
        return jsonify({"error": "Recipient email required."}), 400
    probes, devices, alerts, billing = _gather_report_data(t)
    from app.models.settings import SystemSetting
    brand = SystemSetting.get_value('BRAND_NAME', 'SCARLET')
    pdf = build_tenant_report(t, probes, devices, alerts, billing, brand=brand)
    ok, msg = send_email(to_addr, f"Security Report — {t.name}",
                         f"Attached is the latest security report for {t.name}.",
                         attachments=[(f"report-{t.name}.pdf", pdf, "application/pdf")])
    if ok:
        from app.models.billing import TenantUsage
        TenantUsage.add(t.id, notifications=1)
    _audit('report.email', f"{t.name} -> {to_addr}", tenant_id=t.id)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@bp.route('/notify/test', methods=['POST'])
@login_required
def notify_test():
    if current_user.role != 'superadmin':
        return jsonify({"error": "Unauthorized"}), 403
    from app.services.notify import send_telegram, send_email
    channel = request.form.get('channel')
    target = (request.form.get('target') or '').strip()
    if channel == 'telegram':
        ok, msg = send_telegram(target, "✅ SCARLET test notification — Telegram is configured correctly.")
    elif channel == 'email':
        ok, msg = send_email(target, "SCARLET test email", "This is a test email from SCARLET Command Center.")
    else:
        ok, msg = False, "Unknown channel."
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@bp.route('/')
@login_required
def dashboard():
    import json
    import traceback
    from sqlalchemy import text
    try:
        # FIX: Ensure vulnerabilities column exists on whatever DB this deployment is connected to
        db.session.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS vulnerabilities JSONB;"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    from datetime import datetime, timezone, timedelta

    try:
        scope = _scope_tenant_id()
        pq, dq = Probe.query, Device.query
        if scope:
            pq = pq.filter(Probe.tenant_id == scope)
            dq = dq.filter(Device.tenant_id == scope)
        all_probes = pq.all()
        all_devices = dq.all()
        total_tenants = Tenant.query.count() if (current_user.role == 'superadmin' and not scope) else 1

        total_probes = len(all_probes)
        total_devices = len(all_devices)

        # --- Aggregate KPIs (derived from real data) ---
        now_utc = datetime.now(timezone.utc)
        online_threshold = timedelta(minutes=10)

        probes_online = 0
        status_counts = {"paired": 0, "pending": 0, "scanning": 0, "other": 0}
        for p in all_probes:
            if p.last_seen and (now_utc - p.last_seen) <= online_threshold:
                probes_online += 1
            key = p.status if p.status in status_counts else "other"
            status_counts[key] += 1

        # Device-level metrics: open services/ports, vulnerable assets, ingested data volume
        total_services = 0
        vulnerable_devices = 0
        data_ingested_bytes = 0
        for d in all_devices:
            total_services += len(d.services) if hasattr(d, 'services') else 0
            if d.vulnerabilities:
                vulnerable_devices += 1
                try:
                    data_ingested_bytes += len(json.dumps(d.vulnerabilities))
                except (TypeError, ValueError):
                    pass

        probes_offline = total_probes - probes_online
        online_pct = round((probes_online / total_probes) * 100) if total_probes else 0
        avg_assets = round(total_devices / total_probes, 1) if total_probes else 0

        probes_data = []
        for p in all_probes:
            # Check if coordinates exist
            lat, lng = None, None
            address, contact = "", ""
            if p.metadata_col:
                address = p.metadata_col.get('address', '')
                contact = p.metadata_col.get('contact', '')
                if p.metadata_col.get('coordinates'):
                    coords = p.metadata_col.get('coordinates').split(',')
                    if len(coords) == 2:
                        try:
                            lat = float(coords[0].strip())
                            lng = float(coords[1].strip())
                        except ValueError:
                            pass
            
            device_count = len(p.devices) if hasattr(p, 'devices') else 0
                        
            probes_data.append({
                "id": str(p.id),
                "name": p.probe_name or "Unknown Probe",
                "tenant": p.tenant.name if p.tenant else "Unknown",
                "status": p.status,
                "lat": lat,
                "lng": lng,
                "last_seen": p.last_seen.strftime('%Y-%m-%d %H:%M:%S') if p.last_seen else 'Never',
                "address": address,
                "contact": contact,
                "device_count": device_count
            })
            
        stats = {
            "tenants": total_tenants,
            "probes": total_probes,
            "devices": total_devices,
            "probes_online": probes_online,
            "probes_offline": probes_offline,
            "online_pct": online_pct,
            "status_counts": status_counts,
            "services": total_services,
            "vulnerable_devices": vulnerable_devices,
            "data_ingested_bytes": data_ingested_bytes,
            "avg_assets": avg_assets
        }

        return render_template('admin/map.html', stats=stats, probes_json=json.dumps(probes_data))
    except Exception as e:
        return f"Error rendering dashboard: {str(e)}\n\nTraceback:\n{traceback.format_exc()}", 500

@bp.route('/tenant/create', methods=['POST'])
@login_required
def create_tenant():
    if current_user.role != 'superadmin':
        return "Unauthorized", 403
        
    name = request.form.get('name')
    if name:
        tenant = Tenant(name=name)
        db.session.add(tenant)
        db.session.commit()
        _audit('tenant.create', name, tenant_id=tenant.id)
    return redirect(url_for('admin.tenants'))

@bp.route('/user/create', methods=['POST'])
@login_required
def create_user():
    if current_user.role != 'superadmin':
        return "Unauthorized", 403
        
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password')
    tenant_id = request.form.get('tenant_id')

    if email and password and tenant_id:
        if not User.query.filter_by(email=email).first():
            user = User(email=email, role='tenantadmin', tenant_id=tenant_id)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            _audit('user.create', email, tenant_id=tenant_id)
    return redirect(url_for('admin.tenants'))

@bp.route('/device/scan/<uuid:device_id>', methods=['POST'])
@login_required
def trigger_device_scan(device_id):
    from app.models.probe import Task
    from app.models.device import Device
    
    device = Device.query.get_or_404(device_id)
    
    # Create a new task for the probe
    new_task = Task(
        probe_id=device.probe_id,
        action='vuln_scan',
        target_ip=device.ip_address,
        status='pending'
    )
    db.session.add(new_task)
    db.session.commit()
    
    # Flash a message if we had a flash system, or just redirect
    return redirect(url_for('admin.tenants'))

@bp.route('/license/create', methods=['POST'])
@login_required
def create_license():
    tenant_id = request.form.get('tenant_id')
    if tenant_id:
        if current_user.role == 'superadmin' or str(current_user.tenant_id) == tenant_id:
            license_code = LicenseCode(tenant_id=tenant_id)
            db.session.add(license_code)
            db.session.commit()
            _audit('license.create', tenant_id, tenant_id=tenant_id)
    return redirect(url_for('admin.tenants'))

@bp.route('/probe/<probe_id>/delete', methods=['POST'])
@login_required
def delete_probe(probe_id):
    probe = Probe.query.get(probe_id)
    if probe:
        if current_user.role == 'superadmin' or str(current_user.tenant_id) == str(probe.tenant_id):
            if probe.license:
                probe.license.is_used = False
                probe.license.used_at = None
            db.session.delete(probe)
            db.session.commit()
            _audit('probe.delete', str(probe_id))
    return redirect(url_for('admin.tenants'))

from flask import jsonify


def _create_probe_task(probe_id, action, target_ip='-'):
    """Creates a command Task for a probe after verifying access. Returns (ok, msg)."""
    from app.models.probe import Task
    probe = Probe.query.get(probe_id)
    if not probe:
        return False, "Probe not found."
    if current_user.role != 'superadmin' and str(current_user.tenant_id) != str(probe.tenant_id):
        return False, "Unauthorized."
    task = Task(probe_id=probe.id, action=action, target_ip=target_ip or '-', status='pending')
    db.session.add(task)
    db.session.commit()
    return True, "Command queued. The probe will pick it up on its next heartbeat."


@bp.route('/probe/<probe_id>/suricata/start', methods=['POST'])
@login_required
def suricata_start(probe_id):
    interface = (request.form.get('interface') or '').strip() or '-'
    ok, msg = _create_probe_task(probe_id, 'suricata_start', target_ip=interface)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)
    return redirect(url_for('admin.probes_fleet'))


@bp.route('/probe/<probe_id>/suricata/stop', methods=['POST'])
@login_required
def suricata_stop(probe_id):
    ok, msg = _create_probe_task(probe_id, 'suricata_stop')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)
    return redirect(url_for('admin.probes_fleet'))


# ===========================================================================
# Probe Control Plane — generic command bus
# ===========================================================================
ALLOWED_COMMANDS = {
    'scan_network', 'vuln_scan', 'suricata_start', 'suricata_stop',
    'suricata_reload_rules', 'set_scan_config', 'get_logs', 'get_status',
    'capture_pcap', 'restart_agent', 'factory_reset', 'self_update',
    'scan_wifi', 'scan_ble',
}


def _issue_command(probe, ctype, params):
    """Queues a command for a probe. Returns the created Task."""
    from app.models.probe import Task
    from datetime import datetime, timezone, timedelta
    task = Task(
        probe_id=probe.id,
        action=ctype,
        params=params or {},
        target_ip=(params or {}).get('target_ip') or (params or {}).get('interface'),
        status='pending',
        issued_by=getattr(current_user, 'email', None),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.session.add(task)
    db.session.commit()
    return task


def _command_params_from_request():
    """Builds command params from JSON or form data, excluding the type field."""
    data = request.get_json(silent=True) or request.form.to_dict()
    params = {k: v for k, v in data.items() if k not in ('type', 'command', 'csrf_token')}
    return data.get('type') or data.get('command'), params


@bp.route('/probe/<probe_id>/command', methods=['POST'])
@login_required
def probe_command(probe_id):
    probe = Probe.query.get(probe_id)
    if not probe:
        return jsonify({"error": "Probe not found"}), 404
    if current_user.role != 'superadmin' and str(current_user.tenant_id) != str(probe.tenant_id):
        return jsonify({"error": "Unauthorized"}), 403

    ctype, params = _command_params_from_request()
    if ctype not in ALLOWED_COMMANDS:
        return jsonify({"error": f"Unknown command: {ctype}"}), 400

    task = _issue_command(probe, ctype, params)
    _audit('probe.command', f"{ctype} -> {probe.probe_name or probe.id} {params}", tenant_id=probe.tenant_id)
    return jsonify({"ok": True, "command_id": str(task.id),
                    "message": f"Command '{ctype}' queued. The probe will execute it on its next poll."}), 200


@bp.route('/fleet/command', methods=['POST'])
@login_required
def fleet_command():
    """Issues a command to every probe in the current tenant scope."""
    ctype, params = _command_params_from_request()
    if ctype not in ALLOWED_COMMANDS:
        return jsonify({"error": f"Unknown command: {ctype}"}), 400

    scope = _scope_tenant_id()
    q = Probe.query
    if scope:
        q = q.filter(Probe.tenant_id == scope)
    elif current_user.role != 'superadmin':
        q = q.filter(Probe.tenant_id == current_user.tenant_id)
    probes = q.all()

    count = 0
    for p in probes:
        _issue_command(p, ctype, params)
        count += 1
    _audit('fleet.command', f"{ctype} x{count} {params}")
    return jsonify({"ok": True, "message": f"Command '{ctype}' queued for {count} probe(s)."}), 200


@bp.route('/probe/<probe_id>/commands')
@login_required
def probe_commands(probe_id):
    """JSON timeline of recent commands for a probe (for the console)."""
    from app.models.probe import Task
    probe = Probe.query.get(probe_id)
    if not probe:
        return jsonify({"error": "Probe not found"}), 404
    if current_user.role != 'superadmin' and str(current_user.tenant_id) != str(probe.tenant_id):
        return jsonify({"error": "Unauthorized"}), 403

    tasks = Task.query.filter_by(probe_id=probe.id).order_by(Task.created_at.desc()).limit(40).all()
    out = []
    for t in tasks:
        out.append({
            "id": str(t.id),
            "action": t.action,
            "params": t.params or {},
            "status": t.status,
            "issued_by": t.issued_by,
            "result": t.result,
            "created_at": t.created_at.strftime('%Y-%m-%d %H:%M:%S') if t.created_at else '',
            "completed_at": t.completed_at.strftime('%H:%M:%S') if t.completed_at else '',
        })
    rt = probe.runtime_info or {}
    return jsonify({
        "commands": out,
        "runtime": rt,
        "capabilities": rt.get('capabilities', []),
        "agent_version": rt.get('agent_version'),
    })


@bp.route('/probe/<probe_id>/console')
@login_required
def probe_console(probe_id):
    probe = Probe.query.get(probe_id)
    if not probe:
        return "Probe not found", 404
    if current_user.role != 'superadmin' and str(current_user.tenant_id) != str(probe.tenant_id):
        return "Unauthorized", 403
    return render_template('admin/console.html', probe=probe)


@bp.route('/wireless')
@login_required
def wireless():
    """WiFi access points + BLE devices discovered by the fleet (stored like node discovery)."""
    from app.models.wireless import WifiNetwork, BleDevice
    scope = _scope_tenant_id()
    try:
        wq, bq = WifiNetwork.query, BleDevice.query
        if scope:
            wq = wq.filter(WifiNetwork.tenant_id == scope)
            bq = bq.filter(BleDevice.tenant_id == scope)
        wifi = wq.order_by(WifiNetwork.last_seen.desc()).limit(500).all()
        ble = bq.order_by(BleDevice.last_seen.desc()).limit(500).all()
    except Exception:
        db.session.rollback()
        wifi, ble = [], []
    return render_template('admin/wireless.html', wifi=wifi, ble=ble)


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if current_user.role != 'superadmin':
        return "Unauthorized", 403
        
    from app.models.settings import SystemSetting
    
    # Auto-create table if not exists
    from sqlalchemy import text
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id UUID PRIMARY KEY,
                key VARCHAR NOT NULL UNIQUE,
                value VARCHAR NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE
            )
        """))
        db.session.commit()
    except Exception:
        db.session.rollback()
        
    if request.method == 'POST':
        SystemSetting.set_value('GROQ_API_KEY', request.form.get('groq_api_key', '').strip())
        SystemSetting.set_value('GROQ_MODEL', request.form.get('groq_model', 'llama3-70b-8192').strip())
        SystemSetting.set_value('NVD_API_KEY', request.form.get('nvd_api_key', '').strip())
        SystemSetting.set_value('CVE_CACHE_TTL_DAYS', request.form.get('cve_cache_ttl_days', '30').strip())
        SystemSetting.set_value('GEMINI_API_KEY', request.form.get('gemini_api_key', '').strip())
        SystemSetting.set_value('OLLAMA_API_KEY', request.form.get('ollama_api_key', '').strip())
        SystemSetting.set_value('TELEGRAM_BOT_TOKEN', request.form.get('telegram_bot_token', '').strip())
        SystemSetting.set_value('GMAIL_USER', request.form.get('gmail_user', '').strip())
        SystemSetting.set_value('GMAIL_APP_PASSWORD', request.form.get('gmail_app_password', '').strip())
        SystemSetting.set_value('BRAND_NAME', (request.form.get('brand_name', '').strip() or 'SCARLET'))
        _audit('settings.update', 'global settings saved')
        flash('Settings saved successfully', 'success')
        return redirect(url_for('admin.settings'))
        
    settings_dict = {
        'GROQ_API_KEY': SystemSetting.get_value('GROQ_API_KEY', ''),
        'GROQ_MODEL': SystemSetting.get_value('GROQ_MODEL', 'llama3-70b-8192'),
        'NVD_API_KEY': SystemSetting.get_value('NVD_API_KEY', ''),
        'CVE_CACHE_TTL_DAYS': SystemSetting.get_value('CVE_CACHE_TTL_DAYS', '30'),
        'GEMINI_API_KEY': SystemSetting.get_value('GEMINI_API_KEY', ''),
        'OLLAMA_API_KEY': SystemSetting.get_value('OLLAMA_API_KEY', ''),
        'TELEGRAM_BOT_TOKEN': SystemSetting.get_value('TELEGRAM_BOT_TOKEN', ''),
        'GMAIL_USER': SystemSetting.get_value('GMAIL_USER', ''),
        'GMAIL_APP_PASSWORD': SystemSetting.get_value('GMAIL_APP_PASSWORD', ''),
        'BRAND_NAME': SystemSetting.get_value('BRAND_NAME', 'SCARLET')
    }
    
    return render_template('admin/settings.html', settings=settings_dict)

@bp.route('/device/analyze_vulns/<uuid:device_id>', methods=['POST'])
@login_required
def analyze_vulns(device_id):
    import traceback
    
    try:
        from app.models.settings import SystemSetting
        import json
        import requests
        
        device = Device.query.get_or_404(device_id)
        if current_user.role != 'superadmin' and device.tenant_id != current_user.tenant_id:
            return jsonify({"error": "Unauthorized"}), 403
            
        if not device.vulnerabilities:
            return jsonify({"error": "No vulnerabilities data found for this device."}), 400
            
        api_key = SystemSetting.get_value('GROQ_API_KEY')
        model = SystemSetting.get_value('GROQ_MODEL', 'llama-3.3-70b-versatile')
        
        if not api_key:
            return jsonify({"error": "Groq API Key is not configured. Please contact the administrator or configure it in Settings."}), 400
        
        try:
            # Serialize the vulnerability data
            vuln_json = json.dumps(device.vulnerabilities, indent=2)
            
            prompt = f"""
            You are a senior cybersecurity analyst. Analyze the following Nmap vulnerability scan output for a device with IP {device.ip_address}.
            
            <ScanData>
            {vuln_json}
            </ScanData>
            
            Please provide:
            1. An Executive Summary of the risk level.
            2. A breakdown of the most critical vulnerabilities found (CVEs, impacts).
            3. Clear Remediation Steps.
            
            Format your response using Markdown. Be concise, professional, and highlight critical issues. Do not hallucinate vulnerabilities not present in the data.
            """
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional security analyst. Output clean markdown."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 2048
            }
            
            response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
            
            if response.status_code != 200:
                return jsonify({"error": f"Groq API Error: {response.text}"}), response.status_code
                
            chat_completion = response.json()
            analysis = chat_completion['choices'][0]['message']['content']
            return jsonify({"markdown": analysis}), 200
            
        except Exception as e:
            return jsonify({"error": f"Groq HTTP API Error: {str(e)}\n\n{traceback.format_exc()}"}), 500
    except Exception as e:
        return jsonify({"error": f"Server Error: {str(e)}\n\n{traceback.format_exc()}"}), 500

class NvdError(Exception):
    """Raised when fetching a CVE from the NVD API fails. Carries an HTTP status code
    used by the no-cache path; the lazy-refresh path catches it and falls back to stale data."""
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _cve_to_dict(cve, cached, stale=False, refreshed=False, note=None):
    """Serializes a CveCache row into the JSON payload expected by the frontend."""
    payload = {
        "id": cve.id,
        "description": cve.description,
        "cvss_score": cve.cvss_score,
        "severity": cve.severity,
        "badge_color": cve.badge_color,
        "cached": cached,
        "stale": stale,
        "refreshed": refreshed
    }
    if note:
        payload["note"] = note
    return payload


def _refresh_cve_from_nvd(cve_id, existing=None):
    """Fetches a CVE from the NVD API and upserts it into cve_cache.

    If `existing` is provided, updates that row in place (refreshing cached_at);
    otherwise creates a new CveCache. Returns the CveCache object (not yet committed).
    Raises NvdError on network/HTTP/rate-limit/not-found errors.
    """
    from app.models.cve import CveCache
    from app.models.settings import SystemSetting
    from datetime import datetime, timezone
    from dateutil import parser
    import requests

    nvd_api_key = SystemSetting.get_value('NVD_API_KEY', '')
    headers = {}
    if nvd_api_key:
        headers['apiKey'] = nvd_api_key

    url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}"
    # We add a small timeout to avoid blocking forever. Vercel timeout is usually 10s.
    try:
        resp = requests.get(url, headers=headers, timeout=8)
    except requests.exceptions.RequestException as e:
        raise NvdError(f"Failed to fetch from NVD: {str(e)}", 502)

    if resp.status_code in (403, 429):
        raise NvdError("NVD Rate limit exceeded. Try again later.", 429)
    if resp.status_code != 200:
        raise NvdError(f"NVD API returned {resp.status_code}", resp.status_code)

    data = resp.json()
    if not data.get("vulnerabilities"):
        raise NvdError("CVE not found in NVD.", 404)

    vuln = data["vulnerabilities"][0]["cve"]

    # Parse description
    desc = "No English description available."
    for d in vuln.get("descriptions", []):
        if d.get("lang") == "en":
            desc = d.get("value")
            break

    # Parse CVSS (check cvssMetricV31, then V30, then V2)
    metrics = vuln.get("metrics", {})
    cvss_score = None
    severity = "UNKNOWN"
    for cvss_key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
        if cvss_key in metrics and metrics[cvss_key]:
            metric = metrics[cvss_key][0]
            cvss_data = metric.get("cvssData", {})
            cvss_score = cvss_data.get("baseScore")
            severity = cvss_data.get("baseSeverity", metric.get("baseSeverity", "UNKNOWN"))
            break

    pub_date = None
    if vuln.get("published"):
        pub_date = parser.isoparse(vuln["published"])

    if existing:
        existing.description = desc
        existing.cvss_score = cvss_score
        existing.severity = severity
        existing.published_date = pub_date
        existing.raw_data = vuln
        existing.cached_at = datetime.now(timezone.utc)  # default fires only on insert
        return existing

    new_cve = CveCache(
        id=cve_id,
        description=desc,
        cvss_score=cvss_score,
        severity=severity,
        published_date=pub_date,
        raw_data=vuln
    )
    db.session.add(new_cve)
    return new_cve


@bp.route('/cve/fetch/<cve_id>', methods=['GET'])
@login_required
def fetch_cve(cve_id):
    from app.models.cve import CveCache
    from app.models.settings import SystemSetting
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import text

    # Auto-create table if not exists
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS cve_cache (
                id VARCHAR PRIMARY KEY,
                description TEXT,
                cvss_score FLOAT,
                severity VARCHAR,
                published_date TIMESTAMP WITH TIME ZONE,
                raw_data JSONB,
                cached_at TIMESTAMP WITH TIME ZONE
            )
        """))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Clean input
    cve_id = cve_id.strip().upper()
    if not cve_id.startswith('CVE-'):
        return jsonify({"error": "Invalid CVE ID format."}), 400

    # Resolve the configurable cache TTL (days); fall back to 30 on bad/missing values.
    try:
        ttl_days = int(SystemSetting.get_value('CVE_CACHE_TTL_DAYS', '30') or 30)
    except (ValueError, TypeError):
        ttl_days = 30

    cached = CveCache.query.get(cve_id)

    if cached:
        now_utc = datetime.now(timezone.utc)
        is_expired = cached.cached_at is None or (now_utc - cached.cached_at) > timedelta(days=ttl_days)

        if not is_expired:
            return jsonify(_cve_to_dict(cached, cached=True))

        # Cache expired: try a live refresh from NVD, falling back to stale data on failure.
        try:
            refreshed = _refresh_cve_from_nvd(cve_id, existing=cached)
            db.session.commit()
            return jsonify(_cve_to_dict(refreshed, cached=False, refreshed=True))
        except Exception:
            db.session.rollback()
            return jsonify(_cve_to_dict(
                cached, cached=True, stale=True,
                note="Dati NIST non aggiornabili al momento; mostrati gli ultimi disponibili."
            ))

    # No cache yet: fetch from NVD, surfacing the real error code on failure.
    try:
        new_cve = _refresh_cve_from_nvd(cve_id)
        db.session.commit()
        return jsonify(_cve_to_dict(new_cve, cached=False))
    except NvdError as e:
        db.session.rollback()
        return jsonify({"error": e.message}), e.status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Server Error processing CVE: {str(e)}"}), 500
