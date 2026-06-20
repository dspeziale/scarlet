"""
Parser for nmap "normal" output (-oN -) produced by the probe agent.

Extracts discovered hosts (ip, hostname, mac, vendor) and open services
(port, protocol, service, version) so the server can populate the
device_inventory / service_inventory tables from raw task results.
"""

from __future__ import annotations

import re

# "Nmap scan report for 192.168.1.1"
# "Nmap scan report for host.local (192.168.1.2)"
_HOST_RE = re.compile(r"^Nmap scan report for (?:(?P<name>[^()]+?) \((?P<ip1>[\d.]+)\)|(?P<ip2>[\d.]+))\s*$")
_MAC_RE = re.compile(r"^MAC Address:\s*(?P<mac>[0-9A-Fa-f:]{17})\s*(?:\((?P<vendor>.*)\))?")
# "22/tcp   open  ssh     OpenSSH 8.9p1"
_PORT_RE = re.compile(r"^(?P<port>\d+)/(?P<proto>tcp|udp)\s+open\s+(?P<service>\S+)(?:\s+(?P<version>.*\S))?")


def parse_nmap_hosts(output: str) -> list[dict]:
    """
    Returns a list of discovered devices, each:
        {"ip": str|None, "hostname": str|None, "mac": str|None,
         "vendor": str|None, "services": [{port, protocol, service, version}]}
    """
    if not output:
        return []

    hosts: list[dict] = []
    current: dict | None = None

    for raw in output.splitlines():
        line = raw.rstrip()

        m = _HOST_RE.match(line)
        if m:
            if current:
                hosts.append(current)
            ip = m.group("ip1") or m.group("ip2")
            name = m.group("name")
            current = {
                "ip": ip,
                "hostname": name.strip() if name else None,
                "mac": None,
                "vendor": None,
                "services": [],
            }
            continue

        if current is None:
            continue

        mac = _MAC_RE.match(line.strip())
        if mac:
            current["mac"] = mac.group("mac").upper()
            vendor = mac.group("vendor")
            current["vendor"] = vendor.strip() if vendor else None
            continue

        port = _PORT_RE.match(line.strip())
        if port:
            current["services"].append({
                "port": int(port.group("port")),
                "protocol": port.group("proto"),
                "service": port.group("service"),
                "version": (port.group("version") or None),
            })

    if current:
        hosts.append(current)

    # Keep only hosts that have at least an ip or a mac.
    return [h for h in hosts if h.get("ip") or h.get("mac")]


_BSS_RE = re.compile(r"^BSS\s+([0-9a-fA-F:]{17})")
_SIGNAL_RE = re.compile(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_FREQ_RE = re.compile(r"freq:\s*(\d+)")
_SSID_RE = re.compile(r"SSID:\s*(.*)")


def _freq_to_channel(freq: int) -> int | None:
    if 2412 <= freq <= 2484:
        return 1 if freq == 2412 else (freq - 2407) // 5
    if 5000 <= freq <= 5900:
        return (freq - 5000) // 5
    return None


def parse_iw_scan(output: str) -> list[dict]:
    """Parse `iw <iface> scan` output into wifi network dicts."""
    if not output:
        return []
    nets: list[dict] = []
    cur: dict | None = None
    enc_seen = False
    for raw in output.splitlines():
        line = raw.strip()
        m = _BSS_RE.match(line)
        if m:
            if cur:
                cur["encryption"] = "WPA/WPA2" if enc_seen else "Open"
                nets.append(cur)
            cur = {"bssid": m.group(1).lower(), "ssid": None, "signal": None, "channel": None, "encryption": None}
            enc_seen = False
            continue
        if cur is None:
            continue
        sm = _SIGNAL_RE.search(line)
        if sm:
            cur["signal"] = int(float(sm.group(1)))
        fm = _FREQ_RE.search(line)
        if fm and cur["channel"] is None:
            cur["channel"] = _freq_to_channel(int(fm.group(1)))
        ssm = _SSID_RE.match(line)
        if ssm:
            cur["ssid"] = ssm.group(1).strip() or None
        if "RSN:" in line or "WPA:" in line or "Privacy" in line:
            enc_seen = True
    if cur:
        cur["encryption"] = "WPA/WPA2" if enc_seen else "Open"
        nets.append(cur)
    return [n for n in nets if n.get("bssid")]
