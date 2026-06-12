"""WiFi and BLE scanning for the SCARLET probe.

Both scanners degrade gracefully: if the required tool, interface, hardware or
permission is missing they return an empty list plus a human-readable note,
instead of crashing — mirroring the Suricata manager's behaviour.
"""

import re
import shutil
import subprocess


# ---------------------------------------------------------------------------
# WiFi (nearby access points via `iw scan`, fallback `iwlist`)
# ---------------------------------------------------------------------------
def _freq_to_channel(freq):
    try:
        f = int(freq)
    except (TypeError, ValueError):
        return None
    if f == 2484:
        return 14
    if 2412 <= f <= 2472:
        return (f - 2407) // 5
    if 5000 <= f <= 5900:
        return (f - 5000) // 5
    return None


def _pick_wifi_interface():
    """Returns the first wireless interface name, or None."""
    if shutil.which('iw'):
        try:
            out = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=10).stdout
            m = re.findall(r'Interface\s+(\S+)', out)
            if m:
                return m[0]
        except Exception:
            pass
    return None


def _parse_iw_scan(text):
    aps = []
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'BSS ([0-9a-fA-F:]{17})', line)
        if m:
            if cur:
                aps.append(cur)
            cur = {"bssid": m.group(1).lower(), "ssid": None, "channel": None,
                   "signal": None, "encryption": "Open"}
            continue
        if cur is None:
            continue
        if line.startswith('signal:'):
            sm = re.search(r'(-?\d+\.?\d*)', line)
            if sm:
                cur["signal"] = float(sm.group(1))
        elif line.startswith('freq:'):
            fm = re.search(r'(\d+)', line)
            if fm:
                cur["channel"] = _freq_to_channel(fm.group(1))
        elif line.startswith('SSID:'):
            cur["ssid"] = line[5:].strip()
        elif line.startswith('RSN:'):
            cur["encryption"] = "WPA2/3"
        elif line.startswith('WPA:') and cur["encryption"] == "Open":
            cur["encryption"] = "WPA"
    if cur:
        aps.append(cur)
    return aps


def scan_wifi(interface=None):
    """Returns {"networks": [...], "note": str}."""
    iface = interface or _pick_wifi_interface()
    if not shutil.which('iw'):
        return {"networks": [], "note": "iw tool not installed on probe."}
    if not iface:
        return {"networks": [], "note": "No wireless interface found."}
    try:
        res = subprocess.run(['iw', 'dev', iface, 'scan'], capture_output=True, text=True, timeout=40)
        if res.returncode != 0:
            return {"networks": [], "note": (res.stderr or 'iw scan failed').strip()[-200:]}
        nets = _parse_iw_scan(res.stdout)
        for n in nets:
            ch = n.get("channel")
            n["band"] = ("2.4GHz" if (ch and ch <= 14) else ("5GHz" if ch else None))
            n["hidden"] = not bool(n.get("ssid"))
        return {"networks": nets, "note": f"{len(nets)} access points on {iface}."}
    except Exception as e:
        return {"networks": [], "note": f"WiFi scan error: {e}"}


# ---------------------------------------------------------------------------
# BLE (nearby advertisers via `hcitool lescan`, fallback `bluetoothctl`)
# ---------------------------------------------------------------------------
def scan_ble(timeout=12):
    """Returns {"devices": [...], "note": str}."""
    try:
        timeout = max(3, min(int(timeout), 60))
    except (TypeError, ValueError):
        timeout = 12

    # Preferred: bluetoothctl, which cooperates with the host's BlueZ daemon (no HCI conflict)
    if shutil.which('bluetoothctl'):
        try:
            subprocess.run(['bluetoothctl', '--timeout', str(timeout), 'scan', 'le'],
                           capture_output=True, text=True, timeout=timeout + 8)
            out = subprocess.run(['bluetoothctl', 'devices'], capture_output=True, text=True, timeout=10).stdout
            devs = []
            for line in out.splitlines():
                m = re.match(r'Device\s+([0-9A-Fa-f:]{17})\s+(.*)', line.strip())
                if m:
                    addr = m.group(1).lower()
                    name = m.group(2).strip()
                    # bluetoothctl uses the address (dash form) as a placeholder for unnamed devices
                    if name.replace('-', ':').lower() == addr:
                        name = None
                    devs.append({"address": addr, "name": name, "rssi": None})
            if devs:
                return {"devices": devs, "note": f"{len(devs)} BLE devices (bluetoothctl)."}
        except Exception:
            pass  # fall through to hcitool

    # Fallback: raw HCI LE scan (works when no bluetoothd owns the adapter)
    if shutil.which('hcitool'):
        try:
            res = subprocess.run(['timeout', str(timeout), 'hcitool', 'lescan', '--duplicates'],
                                 capture_output=True, text=True, timeout=timeout + 5)
            seen = {}
            for line in (res.stdout or '').splitlines():
                m = re.match(r'([0-9A-Fa-f:]{17})\s*(.*)', line.strip())
                if m:
                    addr = m.group(1).lower()
                    name = m.group(2).strip()
                    if addr not in seen or (name and name != '(unknown)'):
                        seen[addr] = None if name in ('', '(unknown)') else name
            if seen:
                return {"devices": [{"address": a, "name": n, "rssi": None} for a, n in seen.items()],
                        "note": f"{len(seen)} BLE devices (hcitool)."}
            if res.stderr:
                return {"devices": [], "note": res.stderr.strip()[-200:]}
        except Exception as e:
            return {"devices": [], "note": f"BLE scan error: {e}"}

    return {"devices": [], "note": "No Bluetooth tooling (bluetoothctl/hcitool) on probe."}
