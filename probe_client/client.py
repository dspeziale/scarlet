import os
import json
import requests
import crypto_utils

STATE_FILE = 'probe_state.json'
SERVER_URL = os.environ.get('SERVER_URL', 'http://localhost:5000')

# Probe agent identity & remote-control capabilities advertised to the server.
AGENT_VERSION = "1.4.8"
DEFAULT_POLL = 20
CAPABILITIES = [
    "scan_network", "vuln_scan",
    "suricata_start", "suricata_stop", "suricata_reload_rules",
    "set_scan_config", "get_logs", "get_status", "capture_pcap",
    "scan_wifi", "scan_ble",
    "restart_agent", "factory_reset", "self_update",
]

# Commands that must carry a valid HMAC signature (anti-tamper / anti-replay)
SENSITIVE_COMMANDS = {"restart_agent", "factory_reset", "self_update"}
_processed_command_ids = set()

# Live connection status used by the dashboard "online" LED.
connection_status = {
    "online": False,          # last heartbeat to the server succeeded
    "last_contact": None,     # ISO timestamp of last successful contact
    "last_error": None,
}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "status": "unpaired",
        "probe_id": None,
        "private_key": None,
        "public_key": None,
        "session_token": None,
        "session_key": None
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def reset_state():
    state = {
        "status": "unpaired",
        "probe_id": None,
        "private_key": None,
        "public_key": None,
        "session_token": None,
        "session_key": None,
        "subnet": None
    }
    save_state(state)

def connect_to_server(probe_name="MyProbe", license_code="", tenant_id="", metadata=None):
    state = load_state()
    
    if not license_code or not tenant_id:
        return {"error": "Tenant ID and License code are required for registration"}
        
    # 1. Generate Ephemeral Keypair for the handshake
    priv_key, pub_key = crypto_utils.generate_x25519_keypair()
    state["private_key"] = priv_key
    state["public_key"] = pub_key
    
    # 2. Register
    try:
        payload = {
            "client_public_key": pub_key,
            "probe_name": probe_name,
            "tenant_id": tenant_id,
            "license_code": license_code
        }
        if metadata:
            payload["metadata"] = metadata
            
        reg_resp = requests.post(f"{SERVER_URL}/api/probes/register", json=payload)
        reg_data = reg_resp.json()
        if reg_resp.status_code != 201:
            return {"error": reg_data.get("error", f"Registration failed ({reg_resp.status_code})")}
    except Exception as e:
        return {"error": f"Registration failed: {str(e)}"}
        
    probe_id = reg_data.get("probe_id")
    server_public_key = reg_data.get("server_public_key")
    challenge = reg_data.get("challenge")
    
    state["probe_id"] = probe_id
    
    # 3. Compute Shared Secret & Session Key
    shared_secret = crypto_utils.compute_shared_secret(priv_key, server_public_key)
    session_key = crypto_utils.derive_session_key(shared_secret)
    state["session_key"] = session_key
    
    # 4. Encrypt Challenge
    nonce, ciphertext = crypto_utils.encrypt_aes_gcm(session_key, challenge)
    challenge_response = f"{nonce}:{ciphertext}"
    
    # 5. Complete Handshake
    try:
        handshake_resp = requests.post(f"{SERVER_URL}/api/probes/handshake/complete", json={
            "probe_id": probe_id,
            "client_ephemeral_key": pub_key,
            "challenge_response": challenge_response
        })
        handshake_data = handshake_resp.json()
        if handshake_resp.status_code != 200:
            return {"error": handshake_data.get("error", "Handshake completion failed")}
    except Exception as e:
        return {"error": f"Handshake completion failed: {str(e)}"}
        
    state["status"] = handshake_data.get("status", "paired")
    state["session_token"] = handshake_data.get("session_token")
    
    save_state(state)
    
    # Avvia subito uno scan dopo il pairing
    import threading
    threading.Thread(target=send_scan_data).start()
    
    return {"message": "Successfully connected and paired!", "state": state}

from datetime import datetime
import requests

scan_logs = []

def log_scan(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    scan_logs.append(log_line)
    if len(scan_logs) > 50:
        scan_logs.pop(0)
    print(log_line)

def send_status(status_str):
    """Heartbeat to the server. Returns the next poll interval (seconds) the server
    requests, enabling an adaptive, near-real-time control loop."""
    state = load_state()
    next_poll = DEFAULT_POLL
    if state.get("probe_id"):
        # Report capabilities + current network interfaces + Suricata state
        payload = {
            "probe_id": state["probe_id"],
            "status": status_str,
            "agent_version": AGENT_VERSION,
            "capabilities": CAPABILITIES,
        }
        try:
            import psutil
            payload["cpu"] = psutil.cpu_percent(interval=None)
            payload["mem"] = psutil.virtual_memory().percent
        except Exception:
            pass
        try:
            import suricata_manager
            payload["interfaces"] = [i["name"] for i in suricata_manager.list_interfaces()]
            s = suricata_manager.get_status()
            payload["suricata"] = {
                "running": s.get("running"),
                "interface": s.get("interface"),
                "installed": s.get("installed"),
            }
        except Exception:
            pass
        try:
            resp = requests.post(f"{SERVER_URL}/api/probes/heartbeat", json=payload, timeout=5)
            if resp.status_code == 200:
                connection_status["online"] = True
                connection_status["last_contact"] = datetime.now().isoformat()
                connection_status["last_error"] = None
                data = resp.json()
                next_poll = int(data.get("next_poll", DEFAULT_POLL) or DEFAULT_POLL)
                tasks = data.get("tasks", [])
                if tasks:
                    execute_tasks(tasks, state)
            else:
                connection_status["online"] = False
                connection_status["last_error"] = f"HTTP {resp.status_code}"
        except Exception as e:
            connection_status["online"] = False
            connection_status["last_error"] = str(e)
    return next_poll


def get_connection_info():
    """Returns the live connection state for the dashboard online LED."""
    info = dict(connection_status)
    info["status"] = load_state().get("status", "unpaired")
    return info


def send_suricata_events(events):
    """Encrypts and forwards a batch of Suricata alerts to the central server."""
    if not events:
        return
    state = load_state()
    if state.get("status") != "paired" or not state.get("session_key") or not state.get("probe_id"):
        return
    try:
        payload = json.dumps({"events": events})
        nonce, ciphertext = crypto_utils.encrypt_aes_gcm(state["session_key"], payload)
        requests.post(f"{SERVER_URL}/api/probes/suricata", json={
            "probe_id": state["probe_id"],
            "nonce": nonce,
            "ciphertext": ciphertext
        }, timeout=8)
    except Exception as e:
        log_scan(f"Failed to forward Suricata events: {e}")


def flush_suricata():
    """Drains pending Suricata alerts from the manager and forwards them."""
    try:
        import suricata_manager
        events = suricata_manager.drain_pending()
        if events:
            send_suricata_events(events)
    except Exception:
        pass

# --- Remote command handlers: each takes (params: dict, state: dict) -> result dict ---
def _cmd_vuln_scan(params, state):
    import scanner
    target = params.get('target_ip')
    if not target:
        return {"error": "vuln_scan requires a target_ip"}
    return scanner.vuln_scan(target)


def _cmd_scan_network(params, state):
    subnet = params.get('subnet') or state.get('subnet')
    if subnet and subnet != state.get('subnet'):
        state['subnet'] = subnet
        save_state(state)
    send_scan_data()
    return {"ok": True, "message": "Network scan executed."}


def _cmd_suricata_start(params, state):
    import suricata_manager
    interface = params.get('interface')
    ok, message = suricata_manager.start(interface, server_url=SERVER_URL, probe_id=state.get("probe_id"))
    return {"ok": ok, "message": message, "status": suricata_manager.get_status()}


def _cmd_suricata_stop(params, state):
    import suricata_manager
    ok, message = suricata_manager.stop()
    return {"ok": ok, "message": message, "status": suricata_manager.get_status()}


def _cmd_suricata_reload_rules(params, state):
    import suricata_manager
    st = suricata_manager.get_status()
    interface = params.get('interface') or st.get('interface')
    suricata_manager.stop()
    ok, message = suricata_manager.start(interface, server_url=SERVER_URL, probe_id=state.get("probe_id"))
    return {"ok": ok, "message": f"Rules reloaded. {message}", "status": suricata_manager.get_status()}


def _cmd_set_scan_config(params, state):
    if 'subnet' in params:
        state['subnet'] = (params.get('subnet') or '').strip()
    if 'interval' in params:
        state['scan_interval'] = params.get('interval')
    save_state(state)
    return {"ok": True, "message": "Scan configuration updated.", "subnet": state.get('subnet')}


def _cmd_get_logs(params, state):
    import suricata_manager
    return {"ok": True, "scan_logs": scan_logs[-60:], "suricata_logs": suricata_manager.get_logs()[-120:]}


def _send_encrypted(path, payload, state):
    """Encrypts a JSON payload with the session key and POSTs it to the server."""
    if state.get("status") != "paired" or not state.get("session_key") or not state.get("probe_id"):
        return False
    try:
        nonce, ciphertext = crypto_utils.encrypt_aes_gcm(state["session_key"], json.dumps(payload))
        requests.post(f"{SERVER_URL}{path}", json={
            "probe_id": state["probe_id"], "nonce": nonce, "ciphertext": ciphertext
        }, timeout=10)
        return True
    except Exception as e:
        log_scan(f"Encrypted send to {path} failed: {e}")
        return False


def _cmd_scan_wifi(params, state):
    import wireless
    res = wireless.scan_wifi(params.get('interface'))
    _send_encrypted('/api/probes/wifi', {"networks": res["networks"]}, state)
    return {"ok": True, "note": res["note"], "count": len(res["networks"]), "networks": res["networks"][:20]}


def _cmd_scan_ble(params, state):
    import wireless
    res = wireless.scan_ble(params.get('timeout', 12))
    _send_encrypted('/api/probes/ble', {"devices": res["devices"]}, state)
    return {"ok": True, "note": res["note"], "count": len(res["devices"]), "devices": res["devices"][:20]}


def _cmd_get_status(params, state):
    import suricata_manager
    return {"ok": True, "connection": get_connection_info(), "suricata": suricata_manager.get_status(),
            "subnet": state.get('subnet'), "agent_version": AGENT_VERSION}


def _cmd_restart_agent(params, state):
    import threading, os
    log_scan("Restart requested by server; exiting (container restart policy will relaunch).")
    threading.Timer(1.5, lambda: os._exit(0)).start()
    return {"ok": True, "message": "Agent restarting."}


def _cmd_factory_reset(params, state):
    reset_state()
    return {"ok": True, "message": "Probe factory reset; pairing data wiped."}


def _cmd_self_update(params, state):
    import subprocess, os, threading
    detail = ""
    if os.path.isdir('/app/.git'):
        try:
            detail = subprocess.run(['git', '-C', '/app', 'pull'], capture_output=True, text=True, timeout=60).stdout
        except Exception as e:
            detail = f"git pull failed: {e}"
    log_scan("Self-update requested; restarting agent.")
    threading.Timer(2.0, lambda: os._exit(0)).start()
    return {"ok": True, "message": "Updating & restarting agent.", "detail": detail[-300:]}


def _cmd_capture_pcap(params, state):
    import subprocess, shutil
    if not shutil.which('tcpdump'):
        return {"error": "tcpdump is not installed on this probe."}
    iface = params.get('interface') or ''
    try:
        n = max(1, min(int(params.get('count', 40) or 40), 500))
    except (ValueError, TypeError):
        n = 40
    cmd = ['tcpdump', '-nn', '-l', '-c', str(n)]
    if iface:
        cmd += ['-i', iface]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        lines = (out.stdout or '').strip().splitlines()
        if not lines and out.stderr:
            return {"error": out.stderr.strip()[-300:]}
        return {"ok": True, "count": len(lines), "packets": lines[-n:]}
    except Exception as e:
        return {"error": str(e)}


def _verify_command_signature(task, state):
    """Verifies a sensitive command's HMAC, expiry and replay. Returns (ok, reason)."""
    import hmac, hashlib, base64, json
    from datetime import datetime, timezone
    sig = task.get('sig')
    sk = state.get('session_key')
    if not sk:
        return False, "no session key on probe"
    if not sig:
        return False, "missing signature"
    msg = f"{task['id']}|{task['action']}|{json.dumps(task.get('params') or {}, sort_keys=True)}|{task.get('expires_at') or ''}"
    expected = hmac.new(base64.b64decode(sk), msg.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "bad signature"
    exp = task.get('expires_at')
    if exp:
        try:
            if datetime.now(timezone.utc) > datetime.fromisoformat(exp):
                return False, "command expired"
        except Exception:
            pass
    if task['id'] in _processed_command_ids:
        return False, "replay detected"
    return True, "ok"


COMMAND_HANDLERS = {
    "vuln_scan": _cmd_vuln_scan,
    "scan_network": _cmd_scan_network,
    "suricata_start": _cmd_suricata_start,
    "suricata_stop": _cmd_suricata_stop,
    "suricata_reload_rules": _cmd_suricata_reload_rules,
    "set_scan_config": _cmd_set_scan_config,
    "get_logs": _cmd_get_logs,
    "get_status": _cmd_get_status,
    "scan_wifi": _cmd_scan_wifi,
    "scan_ble": _cmd_scan_ble,
    "restart_agent": _cmd_restart_agent,
    "factory_reset": _cmd_factory_reset,
    "self_update": _cmd_self_update,
    "capture_pcap": _cmd_capture_pcap,
}


def execute_tasks(tasks, state):
    for task in tasks:
        action = task.get('action')
        # Merge legacy target_ip into params for backward compatibility
        params = dict(task.get('params') or {})
        if task.get('target_ip') and 'target_ip' not in params and 'interface' not in params:
            params.setdefault('target_ip', task['target_ip'])
            params.setdefault('interface', task['target_ip'])
        log_scan(f"Command {task.get('id')} :: {action} {params or ''}")

        # Enforce signature/anti-replay on sensitive commands
        if action in SENSITIVE_COMMANDS:
            ok, reason = _verify_command_signature(task, state)
            if not ok:
                log_scan(f"Rejected sensitive command {action}: {reason}")
                try:
                    requests.post(f"{SERVER_URL}/api/probes/task_result", json={
                        "task_id": task['id'], "probe_id": state["probe_id"],
                        "result": {"error": f"Command rejected: {reason}"}
                    }, timeout=10)
                except Exception:
                    pass
                continue
            _processed_command_ids.add(task['id'])

        handler = COMMAND_HANDLERS.get(action)
        try:
            result = handler(params, state) if handler else {"error": f"Unknown command: {action}"}
        except Exception as e:
            import traceback
            result = {"error": str(e), "trace": traceback.format_exc()[-500:]}

        try:
            requests.post(f"{SERVER_URL}/api/probes/task_result", json={
                "task_id": task['id'],
                "probe_id": state["probe_id"],
                "result": result
            }, timeout=15)
            log_scan(f"Command {task.get('id')} done.")
        except Exception as e:
            log_scan(f"Failed to send command result: {e}")

def send_scan_data():
    """Runs a network scan and sends the encrypted results to the server."""
    state = load_state()
    if state.get("status") != "paired" or not state.get("session_key"):
        log_scan("Probe is not paired or missing session key. Aborting.")
        return
        
    log_scan("Starting network scan...")
    send_status("scanning")
    import scanner
    subnet = state.get("subnet")
    try:
        scan_results = scanner.scan_network(subnet)
    except Exception as e:
        log_scan(f"Exception during scan: {str(e)}")
        import traceback
        log_scan(traceback.format_exc())
        send_status("paired")
        return
    
    send_status("paired")
    
    if not scan_results.get("devices"):
        log_scan("No devices found or scan failed silently.")
        return
        
    log_scan(f"Scan completed. Found {len(scan_results['devices'])} devices. Encrypting and sending...")
    
    # Encrypt payload
    json_payload = json.dumps(scan_results)
    nonce, ciphertext = crypto_utils.encrypt_aes_gcm(state["session_key"], json_payload)
    
    try:
        resp = requests.post(f"{SERVER_URL}/api/probes/data", json={
            "probe_id": state["probe_id"],
            "nonce": nonce,
            "ciphertext": ciphertext
        })
        resp.raise_for_status()
        log_scan("Scan data sent successfully to the server.")
    except Exception as e:
        log_scan(f"Failed to send scan data to server: {e}")

# Scheduler setup per run periodico
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

scheduler = BackgroundScheduler()
# Esegue la scansione ogni 30 minuti
scheduler.add_job(func=send_scan_data, trigger="interval", minutes=30)
scheduler.start()

# Spegni lo scheduler quando l'app si ferma
atexit.register(lambda: scheduler.shutdown())
