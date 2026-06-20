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
# OS / device hints from nmap -A / -O
_OS_DETAILS_RE = re.compile(r"^OS details:\s*(.+)")
_RUNNING_RE = re.compile(r"^Running:\s*(.+)")
_DEVICE_TYPE_RE = re.compile(r"^Device type:\s*(.+)")
_SVC_INFO_DEVICE_RE = re.compile(r"Service Info:.*?Device:\s*([\w\- ]+)", re.IGNORECASE)
_SVC_INFO_OS_RE = re.compile(r"Service Info:.*?OS:\s*([^;]+)", re.IGNORECASE)


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
                "os": None,
                "device_hint": None,
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

        ls = line.strip()
        port = _PORT_RE.match(ls)
        if port:
            current["services"].append({
                "port": int(port.group("port")),
                "protocol": port.group("proto"),
                "service": port.group("service"),
                "version": (port.group("version") or None),
            })
            continue

        # OS / device-type hints (from nmap -A / -O)
        om = _OS_DETAILS_RE.match(ls) or _RUNNING_RE.match(ls)
        if om and not current.get("os"):
            current["os"] = om.group(1).strip()
            continue
        dm = _DEVICE_TYPE_RE.match(ls)
        if dm:
            current["device_hint"] = dm.group(1).strip()
            continue
        sd = _SVC_INFO_DEVICE_RE.search(ls)
        if sd and not current.get("device_hint"):
            current["device_hint"] = sd.group(1).strip()
        so = _SVC_INFO_OS_RE.search(ls)
        if so and not current.get("os"):
            current["os"] = so.group(1).strip()

    if current:
        hosts.append(current)

    # Keep only hosts that have at least an ip or a mac.
    return [h for h in hosts if h.get("ip") or h.get("mac")]


_BSS_RE = re.compile(r"^BSS\s+([0-9a-fA-F:]{17})")
_SIGNAL_RE = re.compile(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_FREQ_RE = re.compile(r"freq:\s*(\d+)")
_SSID_RE = re.compile(r"SSID:\s*(.*)")
_LASTSEEN_RE = re.compile(r"last seen:\s*(\d+)\s*ms")
_BEACON_RE = re.compile(r"beacon interval:\s*(\d+)")
_DTIM_RE = re.compile(r"DTIM Period\s*(\d+)")
_COUNTRY_RE = re.compile(r"Country:\s*([A-Z]{2})")
_WIDTH_RE = re.compile(r"STA channel width:\s*(.+)")
_STATIONS_RE = re.compile(r"station count:\s*(\d+)")
_UTIL_RE = re.compile(r"channel utilisation:\s*(\d+)\s*/\s*(\d+)")
_MAXRATE_RE = re.compile(r"max(?:imum)? RX.*?(\d+(?:\.\d+)?)\s*Mbps", re.IGNORECASE)


def _freq_to_channel(freq: int) -> int | None:
    if 2412 <= freq <= 2484:
        return 1 if freq == 2412 else (freq - 2407) // 5
    if 5000 <= freq <= 5900:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:  # 6 GHz (WiFi 6E)
        return (freq - 5950) // 5
    return None


def _band(freq: int | None) -> str | None:
    if not freq:
        return None
    if freq < 2500:
        return "2.4 GHz"
    if freq < 5925:
        return "5 GHz"
    return "6 GHz"


def parse_iw_scan(output: str) -> list[dict]:
    """Parse `iw <iface> scan` output into rich wifi network dicts."""
    if not output:
        return []
    nets: list[dict] = []
    cur: dict | None = None

    def _finalize(n):
        if not n:
            return
        # Encryption summary
        rsn, wpa, wep = n.pop("_rsn", None), n.pop("_wpa", None), n.pop("_privacy", False)
        if rsn:
            n["encryption"] = rsn
        elif wpa:
            n["encryption"] = wpa
        elif wep:
            n["encryption"] = "WEP"
        else:
            n["encryption"] = "Open"
        # 802.11 standard from capabilities seen
        caps = n.pop("_caps", set())
        n["standard"] = ("802.11ax" if "HE" in caps else "802.11ac" if "VHT" in caps
                         else "802.11n" if "HT" in caps else "802.11")
        nets.append(n)

    for raw in output.splitlines():
        line = raw.strip()
        m = _BSS_RE.match(line)
        if m:
            _finalize(cur)
            cur = {"bssid": m.group(1).lower(), "ssid": None, "signal": None, "channel": None,
                   "frequency": None, "band": None, "_caps": set()}
            continue
        if cur is None:
            continue

        sm = _SIGNAL_RE.search(line)
        if sm:
            cur["signal"] = int(float(sm.group(1)))
        fm = _FREQ_RE.search(line)
        if fm and cur["frequency"] is None:
            f = int(fm.group(1))
            cur["frequency"] = f
            cur["channel"] = _freq_to_channel(f)
            cur["band"] = _band(f)
        ssm = _SSID_RE.match(line)
        if ssm:
            cur["ssid"] = ssm.group(1).strip() or None

        for rgx, key, conv in (
            (_LASTSEEN_RE, "last_seen_ms", int), (_BEACON_RE, "beacon_interval", int),
            (_DTIM_RE, "dtim", int), (_COUNTRY_RE, "country", str),
            (_WIDTH_RE, "channel_width", str), (_STATIONS_RE, "stations", int),
        ):
            mm = rgx.search(line)
            if mm and key not in cur:
                cur[key] = conv(mm.group(1).strip())
        um = _UTIL_RE.search(line)
        if um:
            cur["channel_util_pct"] = round(int(um.group(1)) / max(1, int(um.group(2))) * 100)

        # Security / capabilities
        if line.startswith("RSN:"):
            cur["_rsn"] = "WPA2"
        if "Authentication suites:" in line and "_rsn" in cur:
            if "SAE" in line:
                cur["_rsn"] = "WPA3"
            elif "802.1X" in line or "EAP" in line:
                cur["_rsn"] = "WPA2-Enterprise"
            elif "PSK" in line:
                cur["_rsn"] = "WPA2-Personal"
        if line.startswith("WPA:"):
            cur["_wpa"] = "WPA"
        if "Privacy" in line:
            cur["_privacy"] = True
        if "HT capabilities" in line or "HT Capabilities" in line:
            cur["_caps"].add("HT")
        if "VHT capabilities" in line or "VHT Capabilities" in line:
            cur["_caps"].add("VHT")
        if "HE capabilities" in line or "HE Capabilities" in line:
            cur["_caps"].add("HE")
        if "WPS:" in line:
            cur["wps"] = True

    _finalize(cur)
    return [n for n in nets if n.get("bssid")]
