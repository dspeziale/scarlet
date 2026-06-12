"""
Robust Suricata IDS process manager for the SCARLET probe.

Responsibilities:
  * Enumerate the probe's network interfaces (for the UI selector).
  * Start / stop the Suricata process on a chosen interface in a resilient way.
  * Tail Suricata's EVE JSON output, keep a local ring-buffer (for the live
    terminal panel) and expose new alerts to be forwarded to the central server.

Design notes:
  * No import of `client` here -> avoids circular imports. The probe's poller
    drains `drain_pending()` and forwards events using the encrypted channel.
  * Everything degrades gracefully when Suricata is not installed so the UI can
    show a clear, honest status instead of crashing.
"""

import os
import json
import time
import shutil
import signal
import threading
import subprocess
from collections import deque
from datetime import datetime, timezone

LOG_DIR = os.environ.get("SURICATA_LOG_DIR", "/tmp/scarlet_suricata")
EVE_FILE = os.path.join(LOG_DIR, "eve.json")
RULES_FILE = os.path.join(LOG_DIR, "scarlet.rules")
RULES_VERSION_FILE = os.path.join(LOG_DIR, "rules.version")
MAX_BUFFER = 800          # lines kept for the local terminal panel
MAX_PENDING = 500         # alerts awaiting forward to the server

_lock = threading.Lock()
_state = {
    "running": False,
    "interface": None,
    "pid": None,
    "started_at": None,
    "error": None,
}
_process = None
_tail_thread = None
_tail_stop = threading.Event()

_buffer = deque(maxlen=MAX_BUFFER)     # list of {"line": str, "ts": iso}
_pending = deque(maxlen=MAX_PENDING)   # alert dicts not yet forwarded


# ----------------------------------------------------------------------------
# Network interfaces
# ----------------------------------------------------------------------------
def list_interfaces():
    """Returns a list of interfaces: {name, is_up, mac, addresses:[...]}.

    Uses psutil when available, otherwise falls back to /sys/class/net.
    """
    interfaces = []
    try:
        import psutil
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for name, addr_list in addrs.items():
            ipv4, mac = [], None
            for a in addr_list:
                fam = getattr(a, "family", None)
                if fam and int(fam) == 2:            # AF_INET
                    ipv4.append(a.address)
                elif fam and int(fam) in (17, -1):   # AF_PACKET / AF_LINK
                    mac = a.address
            st = stats.get(name)
            interfaces.append({
                "name": name,
                "is_up": bool(st.isup) if st else False,
                "mac": mac,
                "addresses": ipv4,
            })
    except Exception:
        # Fallback: read interface names from the kernel
        net_path = "/sys/class/net"
        if os.path.isdir(net_path):
            for name in sorted(os.listdir(net_path)):
                is_up = False
                try:
                    with open(os.path.join(net_path, name, "operstate")) as f:
                        is_up = f.read().strip() == "up"
                except Exception:
                    pass
                interfaces.append({"name": name, "is_up": is_up, "mac": None, "addresses": []})

    # Push likely-useful interfaces (up, non-loopback) to the top
    interfaces.sort(key=lambda i: (not i["is_up"], i["name"] == "lo", i["name"]))
    return interfaces


# ----------------------------------------------------------------------------
# Process control
# ----------------------------------------------------------------------------
def _suricata_path():
    return shutil.which("suricata")


def _local_rules_version():
    try:
        with open(RULES_VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return None


def sync_rules(server_url, probe_id):
    """Fetches the central IDS ruleset from the server and writes it locally.

    Returns (rules_file_path_or_None, message). Only re-downloads when the server's
    version differs from what we already have on disk.
    """
    import requests
    if not server_url or not probe_id:
        return (RULES_FILE if os.path.exists(RULES_FILE) else None), "No server/probe id; using cached rules."

    have = _local_rules_version() or ""
    try:
        r = requests.get(f"{server_url}/api/probes/rules",
                         params={"probe_id": probe_id, "have": have}, timeout=30)
        if r.status_code != 200:
            return (RULES_FILE if os.path.exists(RULES_FILE) else None), f"Rules sync HTTP {r.status_code}; using cached."
        data = r.json()
    except Exception as e:
        return (RULES_FILE if os.path.exists(RULES_FILE) else None), f"Rules sync failed ({e}); using cached."

    if not data.get("updated"):
        if os.path.exists(RULES_FILE):
            return RULES_FILE, f"Ruleset up to date (v{data.get('version')})."
        return None, "No ruleset configured on the server yet."

    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        with open(RULES_FILE, "w") as f:
            f.write(data.get("rules", ""))
        with open(RULES_VERSION_FILE, "w") as f:
            f.write(data.get("version") or "")
    except Exception as e:
        return None, f"Failed to write rules file: {e}"
    return RULES_FILE, f"Downloaded {data.get('rule_count')} rules (v{data.get('version')})."


def get_status():
    with _lock:
        s = dict(_state)
    # Reconcile: if we think it's running, verify the process is still alive
    if s["running"] and _process is not None and _process.poll() is not None:
        with _lock:
            _state["running"] = False
            _state["error"] = "Suricata process exited unexpectedly."
            s = dict(_state)
    s["installed"] = _suricata_path() is not None
    s["buffered_lines"] = len(_buffer)
    s["rules_version"] = _local_rules_version()
    return s


def _auto_interface():
    """Picks the best capture interface, preferring real physical NICs (wifi/ethernet)
    over virtual ones (docker bridges, veth, virbr)."""
    def score(i):
        name = i["name"]
        s = 0
        if i["is_up"]:
            s += 10
        if i.get("addresses"):
            s += 5
        if name.startswith(("wl", "wlan")):      # wifi
            s += 8
        elif name.startswith(("en", "eth", "eno", "enp")):  # ethernet
            s += 6
        if name.startswith(("br-", "veth", "docker", "virbr", "vmnet")) or name == "lo":
            s -= 20
        return s

    candidates = [i for i in list_interfaces() if i["name"] != "lo" and i["is_up"]]
    if not candidates:
        return None
    best = max(candidates, key=score)
    return best["name"] if score(best) > 0 else None


def start(interface, server_url=None, probe_id=None):
    """Starts Suricata on the given interface, syncing IDS rules from the server first.
    An empty/"auto"/"-" interface (or an unknown one) auto-selects a sensible default.
    Returns (ok, message)."""
    global _process, _tail_thread

    bin_path = _suricata_path()
    if not bin_path:
        with _lock:
            _state["error"] = "Suricata is not installed on this probe."
        return False, "Suricata binary not found. Install the 'suricata' package on the probe host."

    with _lock:
        if _state["running"] and _process is not None and _process.poll() is None:
            return False, f"Suricata is already running on {_state['interface']}."

    # Resolve the interface: accept explicit valid names, otherwise auto-select
    valid = {i["name"] for i in list_interfaces()}
    if not interface or interface in ('-', 'auto') or interface not in valid:
        requested = interface
        interface = _auto_interface()
        if not interface:
            return False, "No suitable network interface found on this probe."
        if requested and requested not in ('-', 'auto'):
            _append_line(f"Requested interface '{requested}' unavailable; auto-selected '{interface}'.")

    os.makedirs(LOG_DIR, exist_ok=True)
    # Fresh eve.json so the tail starts clean
    try:
        open(EVE_FILE, "w").close()
    except Exception:
        pass

    # Sync the centrally-managed ruleset from the server before launching
    rules_file, rules_msg = sync_rules(server_url, probe_id)

    cmd = [bin_path, "-i", interface, "-l", LOG_DIR, "--set", "logging.outputs.1.console.enabled=no"]
    if rules_file and os.path.exists(rules_file):
        cmd += ["-S", rules_file]  # load ONLY the downloaded ruleset
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
        return False, f"Failed to launch Suricata: {e}"

    # Give it a moment; if it dies immediately, surface the stderr reason
    time.sleep(1.0)
    if proc.poll() is not None:
        err = ""
        try:
            err = proc.stderr.read().decode("utf-8", "ignore")[-400:]
        except Exception:
            pass
        with _lock:
            _state.update({"running": False, "error": err or "Suricata exited on startup."})
        return False, f"Suricata failed to start: {err or 'unknown error (check permissions / root).'}"

    _process = proc
    with _lock:
        _state.update({
            "running": True,
            "interface": interface,
            "pid": proc.pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        })
    _append_line(f"Suricata started on {interface} (pid {proc.pid})")
    _append_line(f"Rules: {rules_msg}")

    # Start the tail thread
    _tail_stop.clear()
    _tail_thread = threading.Thread(target=_tail_loop, daemon=True)
    _tail_thread.start()
    return True, f"Suricata started on {interface}. {rules_msg}"


def stop():
    """Stops Suricata gracefully, then forcefully if needed. Returns (ok, message)."""
    global _process
    _tail_stop.set()
    with _lock:
        running = _state["running"]
    if not running or _process is None:
        with _lock:
            _state["running"] = False
        return True, "Suricata is not running."

    try:
        os.killpg(os.getpgid(_process.pid), signal.SIGTERM)
    except Exception:
        try:
            _process.terminate()
        except Exception:
            pass

    try:
        _process.wait(timeout=5)
    except Exception:
        try:
            os.killpg(os.getpgid(_process.pid), signal.SIGKILL)
        except Exception:
            try:
                _process.kill()
            except Exception:
                pass

    with _lock:
        _state.update({"running": False, "pid": None})
    _append_line("Suricata stopped.")
    _process = None
    return True, "Suricata stopped."


# ----------------------------------------------------------------------------
# EVE JSON tailing
# ----------------------------------------------------------------------------
def _append_line(text):
    _buffer.append({
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "line": text,
    })


def _endpoints(evt):
    src = f"{evt.get('src_ip','?')}:{evt.get('src_port','')}".rstrip(":")
    dst = f"{evt.get('dest_ip','?')}:{evt.get('dest_port','')}".rstrip(":")
    return src, dst


def _format_event(evt):
    """Builds a terminal line for any EVE event type. Returns (text, is_alert, severity)."""
    et = evt.get("event_type", "event")
    proto = evt.get("proto", "")
    src, dst = _endpoints(evt)

    if et == "alert":
        a = evt.get("alert", {})
        sev = a.get("severity", "?")
        sig = a.get("signature", "unknown signature")
        sid = a.get("signature_id", "?")
        return f"ALERT sev={sev} {proto} {src} -> {dst} :: {sig} [sid:{sid}]", True, a.get("severity")
    if et == "flow":
        fl = evt.get("flow", {})
        pk = fl.get("pkts_toserver", 0) + fl.get("pkts_toclient", 0)
        by = fl.get("bytes_toserver", 0) + fl.get("bytes_toclient", 0)
        return f"FLOW  {proto} {src} -> {dst} pkts={pk} bytes={by}", False, None
    if et == "http":
        h = evt.get("http", {})
        return f"HTTP  {src} -> {dst} {h.get('http_method','')} {h.get('hostname','')}{h.get('url','')}", False, None
    if et == "dns":
        d = evt.get("dns", {})
        return f"DNS   {src} -> {dst} {d.get('rrname','')} {d.get('rrtype','')}", False, None
    if et == "tls":
        t = evt.get("tls", {})
        return f"TLS   {src} -> {dst} {t.get('sni','')} {t.get('version','')}", False, None
    if et == "stats":
        st = evt.get("stats", {})
        pkts = (st.get("decoder", {}) or {}).get("pkts", "?")
        return f"STATS captured packets={pkts}", False, None
    return f"{et.upper():5} {proto} {src} -> {dst}", False, None


def _tail_loop():
    """Follows eve.json, mirroring every event into the local buffer and a throttled
    forward queue. Alerts are always queued; other event types are sampled to keep the
    upstream volume sane."""
    for _ in range(50):
        if os.path.exists(EVE_FILE) or _tail_stop.is_set():
            break
        time.sleep(0.2)

    try:
        f = open(EVE_FILE, "r")
    except Exception:
        return
    f.seek(0, os.SEEK_END)

    last_fwd = 0.0
    while not _tail_stop.is_set():
        line = f.readline()
        if not line:
            time.sleep(0.3)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue

        text, is_alert, severity = _format_event(evt)
        _append_line(text)  # local terminal: show everything ("packets scrolling")

        # Forward alerts always; throttle other events to ~2/sec to limit upstream volume
        now = time.monotonic()
        if is_alert or (now - last_fwd) > 0.5:
            last_fwd = now
            a = evt.get("alert", {})
            _pending.append({
                "ts": evt.get("timestamp"),
                "event_type": evt.get("event_type"),
                "severity": severity,
                "signature": a.get("signature"),
                "signature_id": a.get("signature_id"),
                "category": a.get("category"),
                "src_ip": evt.get("src_ip"),
                "dest_ip": evt.get("dest_ip"),
                "proto": evt.get("proto"),
                "line": text,
            })
    try:
        f.close()
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Accessors used by the web layer / forwarder
# ----------------------------------------------------------------------------
def get_logs():
    """Returns the local terminal buffer as a list of formatted strings."""
    return [f"[{e['ts']}] {e['line']}" for e in list(_buffer)]


def clear_logs():
    """Clears the local event buffer and truncates eve.json. Returns (ok, message)."""
    _buffer.clear()
    _pending.clear()
    try:
        if os.path.exists(EVE_FILE):
            open(EVE_FILE, "w").close()
    except Exception:
        pass
    _append_line("Logs cleared by administrator.")
    return True, "Suricata logs cleared."


def drain_pending(limit=100):
    """Pops up to `limit` alerts awaiting forward to the central server."""
    out = []
    while _pending and len(out) < limit:
        out.append(_pending.popleft())
    return out
