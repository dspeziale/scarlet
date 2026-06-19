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
