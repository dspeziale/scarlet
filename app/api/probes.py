from flask import Blueprint, request, jsonify
from app.services.handshake_service import HandshakeService
from app.services.probe_service import ProbeService

bp = Blueprint('probes', __name__, url_prefix='/api/probes')

@bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data or 'client_public_key' not in data or 'license_code' not in data:
        return jsonify({"error": "Missing client_public_key or license_code"}), 400
        
    client_public_key = data.get('client_public_key')
    license_code = data.get('license_code')
    tenant_id = data.get('tenant_id')
    probe_name = data.get('probe_name')
    metadata = data.get('metadata')
    
    result = HandshakeService.register_probe(client_public_key, license_code, tenant_id, probe_name, metadata)
    if "error" in result:
        # HandshakeService returns an error dict, we need to handle the status code
        # Actually it returns a dict and we always returned 201 before.
        # But HandshakeService.register_probe now returns a tuple `{"error": ...}, 4xx`
        # Wait, I didn't change HandshakeService.register_probe to return tuples consistently,
        # but the early returns for license errors are tuples. Let's fix that below.
        pass
    
    # Wait, HandshakeService.register_probe might return a tuple now. Let's check the type.
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    
    return jsonify(result), 201

@bp.route('/handshake/complete', methods=['POST'])
def complete_handshake():
    data = request.get_json()
    if not data or not all(k in data for k in ('probe_id', 'client_ephemeral_key', 'challenge_response')):
        return jsonify({"error": "Missing required fields"}), 400
        
    result, status_code = HandshakeService.complete_handshake(
        probe_id=data.get('probe_id'),
        client_ephemeral_key=data.get('client_ephemeral_key'),
        challenge_response=data.get('challenge_response')
    )
    return jsonify(result), status_code

def _meter_bytes(probe, ciphertext):
    """Adds received bytes to the tenant's bandwidth usage (best-effort)."""
    try:
        from app.models.billing import TenantUsage
        TenantUsage.add(probe.tenant_id, bytes_in=len(ciphertext or ''))
    except Exception:
        pass


def _session_key_for(probe):
    """Derives the AES/HMAC session key for a paired probe (base64), or None."""
    from app.core import crypto
    try:
        return crypto.derive_session_key(probe.shared_secret) if probe.shared_secret else None
    except Exception:
        return None


def _sign_command(session_key_b64, td):
    """HMAC-SHA256 signature binding a command to the probe's session key."""
    import hmac, hashlib, base64, json
    key = base64.b64decode(session_key_b64)
    msg = f"{td['id']}|{td['action']}|{json.dumps(td.get('params') or {}, sort_keys=True)}|{td.get('expires_at') or ''}"
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


@bp.route('/heartbeat', methods=['POST'])
def heartbeat():
    from app.core.db import db
    from app.models.probe import Task
    from sqlalchemy import text

    data = request.get_json()
    probe_id = data.get('probe_id') if data else None

    if probe_id:
        probe = ProbeService.get_probe_by_id(probe_id)
        if probe:
            from datetime import datetime, timezone
            # Accumulate CPU-seconds from the reported CPU% over the elapsed interval (metering)
            if 'cpu' in data and probe.last_seen:
                try:
                    elapsed = (datetime.now(timezone.utc) - probe.last_seen).total_seconds()
                    elapsed = max(0, min(elapsed, 120))  # cap to avoid spikes after downtime
                    from app.models.billing import TenantUsage
                    TenantUsage.add(probe.tenant_id, cpu_seconds=(float(data.get('cpu') or 0) / 100.0) * elapsed)
                except Exception:
                    db.session.rollback()

            ProbeService.update_last_seen(probe)
            status = data.get('status')
            if status in ['paired', 'scanning']:
                probe.status = status

            # Store runtime info + capability handshake reported by the probe
            if any(k in data for k in ('interfaces', 'suricata', 'capabilities', 'agent_version', 'cpu')):
                try:
                    db.session.execute(text("ALTER TABLE probes ADD COLUMN IF NOT EXISTS runtime_info JSONB;"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                probe.runtime_info = {
                    "interfaces": data.get('interfaces', []),
                    "suricata": data.get('suricata', {}),
                    "agent_version": data.get('agent_version'),
                    "capabilities": data.get('capabilities', []),
                    "cpu": data.get('cpu'),
                    "mem": data.get('mem'),
                }

            # Fetch and deliver queued commands (HMAC-signed against the session key)
            from datetime import datetime, timezone
            session_key = _session_key_for(probe)
            pending_tasks = Task.query.filter_by(probe_id=probe.id, status='pending').order_by(Task.created_at).all()
            tasks_list = []
            for t in pending_tasks:
                td = {
                    "id": str(t.id),
                    "action": t.action,
                    "target_ip": t.target_ip,
                    "params": t.params or {},
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                }
                if session_key:
                    td["sig"] = _sign_command(session_key, td)
                tasks_list.append(td)
                t.status = 'running'
                t.started_at = datetime.now(timezone.utc)

            db.session.commit()

            # Adaptive heartbeat: poll fast while commands are in flight, slow when idle
            in_flight = len(tasks_list) > 0 or Task.query.filter_by(probe_id=probe.id, status='pending').count() > 0
            next_poll = 3 if in_flight else 20

            return jsonify({"status": "ok", "tasks": tasks_list, "next_poll": next_poll}), 200
            
    return jsonify({"error": "Unauthorized or missing probe_id"}), 401

@bp.route('/task_result', methods=['POST'])
def task_result():
    from app.core.db import db
    from app.models.probe import Task
    from app.models.device import Device
    from datetime import datetime, timezone
    
    data = request.get_json()
    task_id = data.get('task_id')
    probe_id = data.get('probe_id')
    result = data.get('result')
    
    if not task_id or not probe_id:
        return jsonify({"error": "Missing task_id or probe_id"}), 400
        
    task = Task.query.filter_by(id=task_id, probe_id=probe_id).first()
    if not task:
        return jsonify({"error": "Task not found"}), 404
        
    task.status = 'completed'
    task.result = result
    task.completed_at = datetime.now(timezone.utc)
    
    # Save to device if it's a vuln scan
    if task.action == 'vuln_scan':
        device = Device.query.filter_by(probe_id=probe_id, ip_address=task.target_ip).first()
        if device:
            # We can merge or overwrite vulnerabilities
            device.vulnerabilities = result
            
    db.session.commit()
    return jsonify({"message": "Task result saved successfully"}), 200

@bp.route('/data', methods=['POST'])
def receive_data():
    """Receives encrypted scanning data from a probe."""
    import json
    from app.core import crypto
    from app.models.device import Device, DeviceService
    from app.core.db import db
    
    data = request.get_json()
    if not data or not all(k in data for k in ('probe_id', 'nonce', 'ciphertext')):
        return jsonify({"error": "Missing required fields"}), 400
        
    probe = ProbeService.get_probe_by_id(data.get('probe_id'))
    if not probe or probe.status != 'paired' or not probe.shared_secret:
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        session_key = crypto.derive_session_key(probe.shared_secret)
        decrypted_payload = crypto.decrypt_aes_gcm(session_key, data['ciphertext'], data['nonce'])
        scan_results = json.loads(decrypted_payload.decode('utf-8'))
        _meter_bytes(probe, data.get('ciphertext'))
    except Exception as e:
        return jsonify({"error": "Decryption failed"}), 400
        
    # Process scan results
    # scan_results format: {"devices": [{"ip": "...", "mac": "...", "os": "...", "hostname": "...", "snmp": "...", "ports": [{"port": 80, "state": "open", "name": "http", "version": "..."}]}]}
    if 'devices' in scan_results:
        for dev_data in scan_results['devices']:
            device = Device.query.filter_by(tenant_id=probe.tenant_id, ip_address=dev_data.get('ip')).first()
            if not device:
                device = Device(tenant_id=probe.tenant_id, probe_id=probe.id, ip_address=dev_data.get('ip'))
                db.session.add(device)
            
            device.mac_address = dev_data.get('mac', device.mac_address)
            device.os_info = dev_data.get('os', device.os_info)
            device.hostname = dev_data.get('hostname', device.hostname)
            device.snmp_sys_descr = dev_data.get('snmp', device.snmp_sys_descr)
            
            # Flush to get device.id
            db.session.flush()
            
            # Process ports
            if 'ports' in dev_data:
                # Remove old ports (simple sync)
                DeviceService.query.filter_by(device_id=device.id).delete()
                for port_data in dev_data['ports']:
                    service = DeviceService(
                        device_id=device.id,
                        port=port_data.get('port'),
                        protocol=port_data.get('protocol', 'tcp'),
                        state=port_data.get('state'),
                        service_name=port_data.get('name'),
                        service_version=port_data.get('version')
                    )
                    db.session.add(service)
                    
        db.session.commit()
        
    ProbeService.update_last_seen(probe)
    return jsonify({"status": "data received successfully"}), 200

@bp.route('/suricata', methods=['POST'])
def receive_suricata():
    """Receives encrypted Suricata IDS alerts from a paired probe."""
    import json
    from app.core import crypto
    from app.core.db import db
    from app.models.suricata import SuricataEvent
    from sqlalchemy import text

    data = request.get_json()
    if not data or not all(k in data for k in ('probe_id', 'nonce', 'ciphertext')):
        return jsonify({"error": "Missing required fields"}), 400

    probe = ProbeService.get_probe_by_id(data.get('probe_id'))
    if not probe or probe.status != 'paired' or not probe.shared_secret:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        session_key = crypto.derive_session_key(probe.shared_secret)
        decrypted = crypto.decrypt_aes_gcm(session_key, data['ciphertext'], data['nonce'])
        payload = json.loads(decrypted.decode('utf-8'))
        _meter_bytes(probe, data.get('ciphertext'))
    except Exception:
        return jsonify({"error": "Decryption failed"}), 400

    # Ensure the table exists (serverless-safe lazy migration)
    try:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS suricata_events (
                id UUID PRIMARY KEY,
                probe_id UUID NOT NULL,
                tenant_id UUID,
                event_ts VARCHAR,
                event_type VARCHAR,
                severity INTEGER,
                signature VARCHAR,
                signature_id VARCHAR,
                category VARCHAR,
                src_ip VARCHAR,
                dest_ip VARCHAR,
                proto VARCHAR,
                line VARCHAR,
                raw JSONB,
                received_at TIMESTAMP WITH TIME ZONE
            )
        """))
        db.session.execute(text("ALTER TABLE suricata_events ADD COLUMN IF NOT EXISTS event_type VARCHAR;"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    events = payload.get('events', [])
    saved = 0
    for e in events:
        try:
            db.session.add(SuricataEvent(
                probe_id=probe.id,
                tenant_id=probe.tenant_id,
                event_ts=e.get('ts'),
                event_type=e.get('event_type'),
                severity=e.get('severity'),
                signature=e.get('signature'),
                signature_id=str(e.get('signature_id')) if e.get('signature_id') is not None else None,
                category=e.get('category'),
                src_ip=e.get('src_ip'),
                dest_ip=e.get('dest_ip'),
                proto=e.get('proto'),
                line=e.get('line'),
                raw=e,
            ))
            saved += 1
        except Exception:
            continue
    db.session.commit()

    ProbeService.update_last_seen(probe)
    return jsonify({"status": "ok", "saved": saved}), 200

@bp.route('/rules', methods=['GET'])
def get_rules():
    """Serves the centrally-managed Suricata ruleset to a paired probe.

    Query params: probe_id (required, light auth), have (optional current version).
    Returns {updated:false} when the probe already has the latest version.
    """
    from app.models.ids import IdsRuleset
    from sqlalchemy import text
    from app.core.db import db

    probe_id = request.args.get('probe_id')
    probe = ProbeService.get_probe_by_id(probe_id) if probe_id else None
    if not probe or probe.status != 'paired':
        return jsonify({"error": "Unauthorized"}), 401

    # Lazy table creation (serverless-safe)
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

    rs = IdsRuleset.current()
    if not rs or not rs.rules_text:
        return jsonify({"updated": False, "version": None, "rule_count": 0, "rules": ""}), 200

    # Ship only the categories the admin has enabled; version reflects that selection
    from app.services import ids_rules
    active_text, active_version, active_count = ids_rules.active_rules(rs)

    have = request.args.get('have')
    if have and have == active_version:
        return jsonify({"updated": False, "version": active_version, "rule_count": active_count}), 200

    return jsonify({
        "updated": True,
        "version": active_version,
        "rule_count": active_count,
        "rules": active_text,
    }), 200


def _decrypt_probe_payload(data):
    """Validates + decrypts an encrypted probe payload. Returns (probe, dict) or (None, error_response)."""
    import json
    from app.core import crypto
    if not data or not all(k in data for k in ('probe_id', 'nonce', 'ciphertext')):
        return None, (jsonify({"error": "Missing required fields"}), 400)
    probe = ProbeService.get_probe_by_id(data.get('probe_id'))
    if not probe or probe.status != 'paired' or not probe.shared_secret:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    try:
        session_key = crypto.derive_session_key(probe.shared_secret)
        decrypted = crypto.decrypt_aes_gcm(session_key, data['ciphertext'], data['nonce'])
        _meter_bytes(probe, data.get('ciphertext'))
        return probe, json.loads(decrypted.decode('utf-8'))
    except Exception:
        return None, (jsonify({"error": "Decryption failed"}), 400)


@bp.route('/wifi', methods=['POST'])
def receive_wifi():
    """Receives encrypted nearby-WiFi scan results from a paired probe."""
    from app.core.db import db
    from app.models.wireless import WifiNetwork
    from datetime import datetime, timezone

    probe, payload = _decrypt_probe_payload(request.get_json())
    if probe is None:
        return payload  # error tuple

    now = datetime.now(timezone.utc)
    saved = 0
    for n in payload.get('networks', []):
        bssid = (n.get('bssid') or '').lower()
        if not bssid:
            continue
        ap = WifiNetwork.query.filter_by(tenant_id=probe.tenant_id, bssid=bssid).first()
        if not ap:
            ap = WifiNetwork(tenant_id=probe.tenant_id, probe_id=probe.id, bssid=bssid)
            db.session.add(ap)
        ap.probe_id = probe.id
        ap.ssid = n.get('ssid') or ap.ssid
        ap.channel = n.get('channel')
        ap.signal = n.get('signal')
        ap.encryption = n.get('encryption')
        ap.last_seen = now
        saved += 1
    db.session.commit()
    ProbeService.update_last_seen(probe)
    return jsonify({"status": "ok", "saved": saved}), 200


@bp.route('/ble', methods=['POST'])
def receive_ble():
    """Receives encrypted nearby-BLE scan results from a paired probe."""
    from app.core.db import db
    from app.models.wireless import BleDevice
    from datetime import datetime, timezone

    probe, payload = _decrypt_probe_payload(request.get_json())
    if probe is None:
        return payload  # error tuple

    now = datetime.now(timezone.utc)
    saved = 0
    for d in payload.get('devices', []):
        addr = (d.get('address') or '').lower()
        if not addr:
            continue
        dev = BleDevice.query.filter_by(tenant_id=probe.tenant_id, address=addr).first()
        if not dev:
            dev = BleDevice(tenant_id=probe.tenant_id, probe_id=probe.id, address=addr)
            db.session.add(dev)
        dev.probe_id = probe.id
        if d.get('name'):
            dev.name = d.get('name')
        dev.rssi = d.get('rssi')
        dev.last_seen = now
        saved += 1
    db.session.commit()
    ProbeService.update_last_seen(probe)
    return jsonify({"status": "ok", "saved": saved}), 200
