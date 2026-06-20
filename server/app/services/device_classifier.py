"""
Heuristic device-type classifier.

Combines every signal we collect — MAC/OUI vendor, open ports & services,
OS fingerprint, hostname, and nmap's own device hints — into a best-guess
category: router, access_point, switch, printer, ip_camera, nas, smartphone,
tablet, smart_tv, voip_phone, game_console, iot, server, workstation, ...
"""

from __future__ import annotations

# Vendor keyword → category (substring match on the OUI vendor string)
_VENDOR_MAP = {
    "router": ["mikrotik", "tp-link", "tplink", "netgear", "d-link", "dlink", "zyxel",
               "draytek", "fritz", "avm", "technicolor", "sagemcom", "arris", "cradlepoint",
               "fortinet", "sophos", "openwrt"],
    "access_point": ["ubiquiti", "aruba", "ruckus", "meraki", "engenius", "mist"],
    "switch": ["juniper", "brocade", "extreme networks", "allied telesis"],
    "printer": ["hp inc", "hewlett", "canon", "epson", "brother", "lexmark", "xerox",
                "kyocera", "ricoh", "zebra"],
    "ip_camera": ["hikvision", "dahua", "axis communications", "reolink", "foscam",
                  "amcrest", "vivotek", "hanwha", "uniview"],
    "nas": ["synology", "qnap", "western digital", "drobo", "buffalo"],
    "voip_phone": ["polycom", "yealink", "grandstream", "snom", "avaya", "mitel"],
    "smart_tv": ["lg electronics", "vizio", "roku", "tcl", "hisense", "vestel"],
    "media_device": ["sonos", "bose", "harman", "denon", "chromecast"],
    "game_console": ["nintendo", "sony interactive", "microsoft xbox"],
    "smartphone": ["xiaomi", "oneplus", "oppo", "vivo", "realme", "motorola", "nokia",
                   "huawei", "honor"],
    "iot": ["espressif", "raspberry pi", "tuya", "shelly", "sonoff", "itead", "nest",
            "ring", "ecobee", "philips lighting", "signify", "tado", "particle",
            "texas instruments", "arduino"],
}

# Ambiguous vendors handled with extra signals
_AMBIGUOUS = {"apple", "samsung", "google", "amazon", "intel", "dell", "lenovo",
              "asustek", "asus", "micro-star", "gigabyte", "cisco"}

# Port/service signatures → category
_PORT_SIGNATURES = [
    ("printer", {9100, 631, 515}),
    ("ip_camera", {554, 8554}),
    ("nas", {2049, 548, 5000, 5001}),
    ("voip_phone", {5060, 5061}),
    ("media_device", {8008, 8009, 1400}),
    ("router", {53}),  # weak — only with web admin, handled below
]


def _ports_of(services) -> set[int]:
    out = set()
    for s in services or []:
        p = s.get("port")
        if isinstance(p, int):
            out.add(p)
    return out


def classify(device: dict, services=None) -> str:
    vendor = (device.get("vendor") or "").lower()
    os_str = (device.get("os") or "").lower()
    host = (device.get("hostname") or "").lower()
    hint = (device.get("device_hint") or "").lower()
    ports = _ports_of(services if services is not None else (device.get("details") or {}).get("services"))

    # 1. nmap's explicit device hint is high quality
    for key, cat in (("router", "router"), ("webcam", "ip_camera"), ("camera", "ip_camera"),
                     ("phone", "smartphone"), ("printer", "printer"), ("switch", "switch"),
                     ("WAP", "access_point"), ("media device", "media_device"),
                     ("broadband router", "router"), ("storage", "nas"),
                     ("game console", "game_console")):
        if key.lower() in hint:
            return cat

    # 2. Hostname patterns
    host_rules = [
        ("smartphone", ["iphone", "android", "galaxy", "pixel", "redmi", "huawei-"]),
        ("tablet", ["ipad", "tablet", "tab-", "-tab"]),
        ("smart_tv", ["tv", "bravia", "aquos", "shield"]),
        ("printer", ["printer", "officejet", "laserjet", "epson", "canon"]),
        ("nas", ["nas", "diskstation", "synology", "qnap", "freenas", "truenas"]),
        ("ip_camera", ["camera", "ipcam", "cam-", "hikvision", "dahua"]),
        ("router", ["router", "gateway", "openwrt", "fritz", "gw-"]),
        ("access_point", ["accesspoint", "-ap", "ap-", "unifi"]),
    ]
    for cat, kws in host_rules:
        if any(k in host for k in kws):
            return cat

    # 3. Vendor OUI map (unambiguous vendors)
    for cat, kws in _VENDOR_MAP.items():
        if any(k in vendor for k in kws):
            return cat

    # 4. Port/service signatures
    has_web = bool(ports & {80, 443, 8080, 8443})
    for cat, sig in _PORT_SIGNATURES:
        if cat == "router":
            if 53 in ports and has_web:
                return "router"
            continue
        if ports & sig:
            return cat

    # 5. OS fingerprint
    if "android" in os_str:
        return "tablet" if "tab" in host else "smartphone"
    if "ios" in os_str or "iphone os" in os_str:
        return "smartphone"
    if "windows" in os_str:
        return "server" if "server" in os_str else "workstation"
    if "mac os" in os_str or "macos" in os_str or "darwin" in os_str:
        return "workstation"

    # 6. Ambiguous vendors resolved by OS / ports
    if any(a in vendor for a in _AMBIGUOUS):
        if "apple" in vendor:
            return "workstation" if (ports & {22, 445, 5900}) else "smartphone"
        if vendor.startswith("cisco"):
            return "router" if has_web else "network_device"
        if any(v in vendor for v in ("dell", "lenovo", "asus", "intel", "micro-star", "gigabyte")):
            return "workstation"
        # samsung/google/amazon: TV/IoT if no PC ports
        return "iot" if not (ports & {22, 3389, 445}) else "workstation"

    # 7. Generic fallbacks by ports
    if ports & {3389, 445, 139} or ports & {22} and "linux" in os_str:
        # many server-ish ports → server, otherwise workstation
        return "server" if len(ports) >= 4 or (ports & {3306, 5432, 25, 110, 143}) else "workstation"
    if has_web and 53 in ports:
        return "router"
    if "linux" in os_str:
        return "server" if len(ports) >= 3 else "iot"

    return "unknown"
