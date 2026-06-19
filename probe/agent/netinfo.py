"""
Network discovery on the probe host.

Enumerates the available network interfaces and the subnets the probe is
attached to, so the server console can present them and let an operator choose
which card Suricata should listen on.

Primary backend: psutil (already an optional dependency). Falls back to parsing
`ip -j addr` (iproute2, JSON output) when psutil is unavailable.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess

import structlog

log = structlog.get_logger("agent.netinfo")

# Interfaces that carry no useful capture surface — never offered as a choice.
_SKIP_PREFIXES = ("lo", "docker", "br-", "veth", "vmnet", "vboxnet")


def collect_network_info() -> dict:
    """
    Returns:
        {
          "interfaces": [
            {"name": "eth0", "mac": "..", "is_up": true,
             "addresses": [{"family": "ipv4", "address": "192.168.1.5",
                            "netmask": "255.255.255.0", "cidr": "192.168.1.5/24"}],
             "subnets": ["192.168.1.0/24"]},
            ...
          ],
          "subnets": ["192.168.1.0/24", ...]   # deduplicated, all interfaces
        }
    """
    try:
        info = _collect_psutil()
    except ImportError:
        info = _collect_ip_cmd()
    except Exception as exc:
        log.warning("netinfo_collect_failed", error=str(exc))
        info = {"interfaces": [], "subnets": []}

    log.info(
        "network_info_collected",
        interfaces=[i["name"] for i in info["interfaces"]],
        subnets=info["subnets"],
    )
    return info


def _is_capture_candidate(name: str) -> bool:
    return not name.startswith(_SKIP_PREFIXES)


def _network_cidr(address: str, netmask: str) -> str | None:
    try:
        iface = ipaddress.ip_interface(f"{address}/{netmask}")
        return str(iface.network)
    except ValueError:
        return None


def _addr_cidr(address: str, netmask: str) -> str | None:
    try:
        return str(ipaddress.ip_interface(f"{address}/{netmask}"))
    except ValueError:
        return None


# ── psutil backend ──────────────────────────────────────────────────────────

def _collect_psutil() -> dict:
    import psutil  # optional dependency — ImportError handled by caller

    if_addrs = psutil.net_if_addrs()
    if_stats = psutil.net_if_stats()

    interfaces: list[dict] = []
    all_subnets: set[str] = set()

    for name, addrs in if_addrs.items():
        if not _is_capture_candidate(name):
            continue
        mac = None
        addresses: list[dict] = []
        subnets: set[str] = set()

        for a in addrs:
            if a.family == psutil.AF_LINK:
                mac = a.address
            elif a.family == socket.AF_INET:
                cidr = _addr_cidr(a.address, a.netmask or "255.255.255.255")
                net = _network_cidr(a.address, a.netmask or "255.255.255.255")
                addresses.append({
                    "family": "ipv4", "address": a.address,
                    "netmask": a.netmask, "cidr": cidr,
                })
                if net:
                    subnets.add(net)
            elif a.family == socket.AF_INET6:
                addresses.append({
                    "family": "ipv6", "address": a.address.split("%")[0],
                    "netmask": a.netmask, "cidr": None,
                })

        stats = if_stats.get(name)
        interfaces.append({
            "name": name,
            "mac": mac,
            "is_up": bool(stats.isup) if stats else None,
            "addresses": addresses,
            "subnets": sorted(subnets),
        })
        all_subnets.update(subnets)

    return {"interfaces": interfaces, "subnets": sorted(all_subnets)}


# ── iproute2 fallback ─────────────────────────────────────────────────────────

def _collect_ip_cmd() -> dict:
    proc = subprocess.run(
        ["ip", "-j", "addr", "show"],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ip addr failed: {proc.stderr}")
    links = json.loads(proc.stdout or "[]")

    interfaces: list[dict] = []
    all_subnets: set[str] = set()

    for link in links:
        name = link.get("ifname", "")
        if not name or not _is_capture_candidate(name):
            continue
        addresses: list[dict] = []
        subnets: set[str] = set()

        for ai in link.get("addr_info", []):
            local = ai.get("local")
            prefix = ai.get("prefixlen")
            if not local or prefix is None:
                continue
            family = "ipv4" if ai.get("family") == "inet" else "ipv6"
            cidr = f"{local}/{prefix}"
            if family == "ipv4":
                net = _network_cidr(local, str(prefix))
                addresses.append({"family": family, "address": local,
                                  "netmask": str(prefix), "cidr": cidr})
                if net:
                    subnets.add(net)
            else:
                addresses.append({"family": family, "address": local,
                                  "netmask": str(prefix), "cidr": None})

        interfaces.append({
            "name": name,
            "mac": link.get("address"),
            "is_up": link.get("operstate") == "UP",
            "addresses": addresses,
            "subnets": sorted(subnets),
        })
        all_subnets.update(subnets)

    return {"interfaces": interfaces, "subnets": sorted(all_subnets)}
