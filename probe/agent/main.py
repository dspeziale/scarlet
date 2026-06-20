"""
Probe agent entry point.

Boot sequence:
  1. Load config
  2. Load or generate cryptographic identity
  3. Register with server (one-time, uses REGISTRATION_TOKEN)
  4. Key provisioning handshake (X25519 DH)
  5. Fetch IDS config from server
  6. Start Suricata with received config
  7. Spawn worker threads:
       - HeartbeatWorker   (heartbeat + task polling)
       - RuleUpdater        (poll for ruleset changes)
       - AlertReporter      (tail eve.json, batch-send alerts)
       - PcapUploader       (watch pcap dir, upload completed files)
  8. Main thread loops on signal or keyboard interrupt
"""

from __future__ import annotations

import json
import platform as _platform
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid as _uuid
from pathlib import Path
from typing import Optional

import httpx
import structlog

from config import ProbeConfig, cfg
from crypto_client import ProbeKeys
from local_queue import LocalQueue
from netinfo import collect_network_info
from suricata_manager import SuricataManager
from rule_updater import RuleUpdater
from alert_reporter import AlertReporter
from pcap_uploader import PcapUploader
from heartbeat import HeartbeatWorker

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("agent.main")


class ProbeAgent:
    def __init__(self) -> None:
        self.probe_id: str = cfg.PROBE_ID
        self._keys = ProbeKeys(cfg.KEY_FILE)
        self._queue = LocalQueue(cfg.QUEUE_DB)
        self._http = self._make_client()
        self._suricata = SuricataManager(
            yaml_template=cfg.SURICATA_YAML_TEMPLATE,
            yaml_live=cfg.SURICATA_YAML,
            rules_path=cfg.SURICATA_RULES_PATH,
            log_dir=cfg.SURICATA_LOG_DIR,
        )
        self._workers: list = []
        self._running = False
        # Network info (interfaces + subnets) collected at boot, reported to server.
        self._network: dict = {"interfaces": [], "subnets": []}
        # Capture interface chosen from the server console. Suricata stays OFF
        # until an ids_start task arrives carrying (or having previously set) it.
        self._selected_interface: Optional[str] = None

    # ── HTTP ─────────────────────────────────────────────────────────────

    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            verify=cfg.VERIFY_TLS,
            timeout=30.0,
        )

    def _set_auth_header(self, access_token: str) -> None:
        self._http.headers.update({"Authorization": f"Bearer {access_token}"})

    # ── Registration ─────────────────────────────────────────────────────

    def _load_state(self) -> Optional[dict]:
        if cfg.STATE_DB.exists():
            try:
                return json.loads(cfg.STATE_DB.read_text())
            except Exception:
                pass
        return None

    def _save_state(self, state: dict) -> None:
        cfg.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
        cfg.STATE_DB.write_text(json.dumps(state, indent=2))

    def _register(self) -> dict:
        """POST /api/v1/probes/register — returns {probe_id, access_token, ...}"""
        if not cfg.REGISTRATION_TOKEN:
            raise RuntimeError("REGISTRATION_TOKEN is required for first-time registration")
        hostname = socket.gethostname()
        try:
            machine_id = Path("/etc/machine-id").read_text().strip()
        except Exception:
            machine_id = str(_uuid.uuid4())
        payload = {
            "registration_token": cfg.REGISTRATION_TOKEN,
            "hostname": hostname,
            "machine_id": machine_id,
            "agent_version": cfg.AGENT_VERSION,
            "platform": _platform.system(),
            "architecture": _platform.machine(),
            "sign_public_key": self._keys.sign_public_hex,
            "exchange_public_key": self._keys.exchange_public_hex,
            "network": self._network,
        }
        log.info("registering_probe")
        resp = self._http.post(
            f"{cfg.SERVER_URL}/api/v1/probes/register",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _provision_keys(self, probe_id: str) -> dict:
        """POST /api/v1/probes/<id>/provision — DH handshake."""
        payload = {
            "sign_public_key": self._keys.sign_public_hex,
            "exchange_public_key": self._keys.exchange_public_hex,
        }
        resp = self._http.post(
            f"{cfg.SERVER_URL}/api/v1/probes/{probe_id}/provision",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _authenticate(self) -> str:
        """POST /api/v1/auth/probe-login — returns JWT access token."""
        resp = self._http.post(
            f"{cfg.SERVER_URL}/api/v1/auth/probe-login",
            json={"probe_id": self.probe_id, "sign_public_key": self._keys.sign_public_hex},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # ── IDS Config ───────────────────────────────────────────────────────

    def _fetch_ids_config(self) -> Optional[dict]:
        try:
            resp = self._http.get(
                f"{cfg.SERVER_URL}/api/v1/probes/{self.probe_id}/ids/config",
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            log.warning("fetch_ids_config_failed", error=str(exc))
        return None

    # ── Task handling ─────────────────────────────────────────────────────

    # ── Task helpers ──────────────────────────────────────────────────────

    def _run(self, cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
        """Run a subprocess and return (returncode, stdout, stderr)."""
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _nmap(self, args: list[str], timeout: int = 1800) -> dict:
        """Run nmap and return structured result."""
        rc, stdout, stderr = self._run(["nmap", "-oN", "-"] + args, timeout=timeout)
        return {
            "status": "ok" if rc == 0 else "error",
            "output": stdout,
            "stderr": stderr or None,
        }

    def _ble_scan(self, duration: int) -> dict:
        """
        Scan for BLE devices using bluetoothctl talking to the host's bluetoothd
        over the mounted system D-Bus socket. Requires:
          - a physical Bluetooth controller on the host (powered, unblocked)
          - the container started with  -v /var/run/dbus:/var/run/dbus
        """
        # 1. Is a controller reachable?
        rc, out, err = self._run(["bluetoothctl", "list"], timeout=10)
        if rc != 0 or not out.strip():
            return {
                "status": "error",
                "error": "no Bluetooth controller reachable — ensure the host has a "
                         "powered adapter and the container was started with "
                         "-v /var/run/dbus:/var/run/dbus",
                "stderr": err or None,
            }
        controller = out.strip().splitlines()[0]

        # 2. Power on + timed LE scan (blocks for `duration` seconds).
        self._run(["bluetoothctl", "power", "on"], timeout=10)
        self._run(
            ["bluetoothctl", "--timeout", str(duration), "scan", "on"],
            timeout=duration + 15,
        )

        # 3. Enumerate discovered devices.
        rc, dev_out, dev_err = self._run(["bluetoothctl", "devices"], timeout=15)
        devices = []
        for line in dev_out.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device":
                devices.append({
                    "address": parts[1],
                    "name": parts[2] if len(parts) > 2 else None,
                })

        return {
            "status": "ok",
            "controller": controller,
            "duration": duration,
            "count": len(devices),
            "devices": devices,
        }

    def _handle_task(self, task: dict) -> None:
        task_type = task.get("type")
        task_id = task.get("id")
        payload = task.get("payload") or {}
        log.info("task_received", task_type=task_type, task_id=task_id)
        result = {"status": "ok"}

        try:
            # ── IDS / Suricata tasks ─────────────────────────────────────
            if task_type == "ids_start":
                # Suricata can only start once a capture interface is chosen
                # from the server console. The interface may travel with this
                # task, or have been set by an earlier config_update.
                interface = payload.get("interface") or self._selected_interface
                if not interface:
                    result = {
                        "status": "error",
                        "error": "no capture interface selected — choose a network card from the console first",
                        "available_interfaces": [i["name"] for i in self._network.get("interfaces", [])],
                    }
                else:
                    self._selected_interface = interface
                    self._suricata.apply_config(
                        interface=interface,
                        bpf_filter=payload.get("bpf_filter", ""),
                        capture_mode=payload.get("capture_mode", cfg.DEFAULT_CAPTURE_MODE),
                    )
                    ok = self._suricata.start()
                    result = {"status": "ok" if ok else "error", "started": ok, "interface": interface}
                    if not ok:
                        result["error"] = self._suricata.last_error or "Suricata failed to start (see probe logs)"

            elif task_type == "ids_stop":
                self._suricata.stop()

            elif task_type == "ids_restart":
                ok = self._suricata.restart()
                result = {"status": "ok" if ok else "error"}

            elif task_type == "ids_status":
                result = self._suricata.status()

            elif task_type == "ids_rule_deploy":
                rules_content = payload.get("rules_content", "")
                version = payload.get("version", "")
                if rules_content:
                    cfg.SURICATA_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
                    cfg.SURICATA_RULES_PATH.write_text(rules_content)
                    if self._suricata.is_running():
                        self._suricata.reload_rules()
                    result = {"status": "ok", "version_applied": version}

            elif task_type in ("pcap_start", "pcap_stop"):
                result = {"status": "ok", "note": "pcap controlled via suricata config"}

            elif task_type == "config_update":
                if payload:
                    interface = payload.get("interface") or self._selected_interface or cfg.DEFAULT_INTERFACE
                    self._selected_interface = interface
                    self._suricata.apply_config(
                        interface=interface,
                        bpf_filter=payload.get("bpf_filter", ""),
                        capture_mode=payload.get("capture_mode", cfg.DEFAULT_CAPTURE_MODE),
                    )
                    # Only restart if already running — config_update never starts IDS.
                    if self._suricata.is_running():
                        self._suricata.restart()
                    result = {"status": "ok", "interface": interface}

            # ── Network discovery tasks ───────────────────────────────────
            elif task_type == "network_discovery":
                target = payload.get("target", "")
                if not target:
                    result = {"status": "error", "error": "target required"}
                else:
                    # Big default so wide subnet sweeps don't time out. Override via payload.timeout (seconds).
                    timeout_sec = int(payload.get("timeout", 1800))
                    result = self._nmap(
                        ["-sn", "--host-timeout", f"{timeout_sec}s", target],
                        timeout=timeout_sec + 60,
                    )

            elif task_type == "service_detection":
                target = payload.get("target", "")
                ports = payload.get("ports", "1-1024")
                if not target:
                    result = {"status": "error", "error": "target required"}
                else:
                    timeout_sec = int(payload.get("timeout", 3600))
                    result = self._nmap(
                        ["-sV", "--open", "-p", str(ports), target],
                        timeout=timeout_sec,
                    )

            elif task_type == "os_fingerprinting":
                target = payload.get("target", "")
                if not target:
                    result = {"status": "error", "error": "target required"}
                else:
                    # -O requires root; fall back to -A (aggressive, works without root)
                    timeout_sec = int(payload.get("timeout", 2400))
                    result = self._nmap(["-A", "--open", target], timeout=timeout_sec)

            elif task_type == "snmp_inventory":
                target = payload.get("target", "")
                community = payload.get("community", "public")
                if not target:
                    result = {"status": "error", "error": "target required"}
                else:
                    rc, stdout, stderr = self._run(
                        ["snmpwalk", "-v2c", "-c", community, target],
                        timeout=int(payload.get("timeout", 300)),
                    )
                    result = {
                        "status": "ok" if rc == 0 else "error",
                        "output": stdout,
                        "stderr": stderr or None,
                    }

            elif task_type == "wifi_scan":
                duration = int(payload.get("duration", 10))
                rc, stdout, stderr = self._run(
                    ["iw", "dev"], timeout=10
                )
                if rc != 0:
                    result = {"status": "error", "error": "iw not available or no wireless interfaces"}
                else:
                    # Parse interface name from `iw dev` output
                    iface = None
                    for line in stdout.splitlines():
                        line = line.strip()
                        if line.startswith("Interface "):
                            iface = line.split()[-1]
                            break
                    if not iface:
                        result = {"status": "error", "error": "no wireless interface found"}
                    else:
                        rc2, out2, err2 = self._run(
                            ["iw", iface, "scan"], timeout=duration + 10
                        )
                        result = {
                            "status": "ok" if rc2 == 0 else "error",
                            "interface": iface,
                            "output": out2,
                            "stderr": err2 or None,
                        }

            elif task_type == "ble_scan":
                duration = int(payload.get("duration", 10))
                result = self._ble_scan(duration)

            elif task_type == "custom_script":
                script = payload.get("script", "")
                timeout_sec = int(payload.get("timeout", 600))
                if not script:
                    result = {"status": "error", "error": "script required"}
                else:
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".sh", delete=False
                    ) as tmp:
                        tmp.write(script)
                        tmp_path = tmp.name
                    try:
                        rc, stdout, stderr = self._run(
                            ["bash", tmp_path], timeout=timeout_sec
                        )
                        result = {
                            "status": "ok" if rc == 0 else "error",
                            "returncode": rc,
                            "stdout": stdout,
                            "stderr": stderr or None,
                        }
                    finally:
                        Path(tmp_path).unlink(missing_ok=True)

            elif task_type == "ping":
                target = payload.get("target", "")
                count = int(payload.get("count", 4))
                if not target:
                    result = {"status": "error", "error": "target required"}
                else:
                    rc, stdout, stderr = self._run(
                        ["ping", "-c", str(count), target], timeout=max(60, count * 2 + 30)
                    )
                    result = {
                        "status": "ok" if rc == 0 else "error",
                        "output": stdout,
                        "reachable": rc == 0,
                    }

            else:
                log.warning("unknown_task_type", task_type=task_type)
                result = {"status": "error", "error": f"unknown task type: {task_type}"}

        except subprocess.TimeoutExpired:
            log.warning("task_timeout", task_id=task_id, task_type=task_type)
            result = {"status": "error", "error": "task timed out"}
        except Exception as exc:
            log.error("task_execution_error", task_id=task_id, error=str(exc))
            result = {"status": "error", "error": str(exc)}

        # Report result
        try:
            self._http.post(
                f"{cfg.SERVER_URL}/api/v1/probes/{self.probe_id}/tasks/{task_id}/result",
                json={"result": result},
                timeout=15,
            )
        except Exception:
            log.warning("task_result_report_failed", task_id=task_id)

    # ── Boot ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        # Read available network interfaces + subnets up front so they can be
        # reported to the server at registration and on every heartbeat.
        self._network = collect_network_info()

        state = self._load_state()

        if state and state.get("probe_id"):
            self.probe_id = state["probe_id"]
            log.info("probe_identity_loaded", probe_id=self.probe_id)
            # Re-authenticate
            try:
                access_token = self._authenticate()
                self._set_auth_header(access_token)
            except Exception as exc:
                log.error("auth_failed", error=str(exc))
                sys.exit(1)
        else:
            # First-time registration
            reg = self._register()
            self.probe_id = reg["probe_id"]
            # Provisioning handshake (DH key exchange)
            self._provision_keys(self.probe_id)
            self._set_auth_header(reg.get("access_token", ""))
            self._save_state({"probe_id": self.probe_id})
            log.info("probe_registered", probe_id=self.probe_id)

        # IDS stays OFF at boot. Suricata is only started by an explicit
        # ids_start task from the server console, after an interface has been
        # chosen. We still query the server in case a card was already selected
        # previously (so the console can show it), but we never auto-start.
        self._suricata.stop()  # clear any stale process/pidfile from a prior run
        ids_cfg = self._fetch_ids_config()
        if ids_cfg and ids_cfg.get("interface"):
            self._selected_interface = ids_cfg.get("interface")
        log.info("ids_idle_awaiting_console", selected_interface=self._selected_interface)

        # Worker threads
        rule_updater = RuleUpdater(
            server_url=cfg.SERVER_URL,
            probe_id=self.probe_id,
            rules_path=cfg.SURICATA_RULES_PATH,
            check_interval=cfg.RULE_CHECK_INTERVAL,
            http_client=self._http,
            suricata_reload_fn=self._suricata.reload_rules,
        )
        alert_reporter = AlertReporter(
            server_url=cfg.SERVER_URL,
            probe_id=self.probe_id,
            eve_log=cfg.SURICATA_EVE_LOG,
            flush_interval=cfg.ALERT_FLUSH_INTERVAL,
            http_client=self._http,
            queue=self._queue,
        )
        pcap_uploader = PcapUploader(
            server_url=cfg.SERVER_URL,
            probe_id=self.probe_id,
            pcap_dir=cfg.PCAP_DIR,
            http_client=self._http,
            queue=self._queue,
        )
        heartbeat = HeartbeatWorker(
            server_url=cfg.SERVER_URL,
            probe_id=self.probe_id,
            interval=cfg.HEARTBEAT_INTERVAL,
            http_client=self._http,
            get_ids_status=self._suricata.status,
            task_handler=self._handle_task,
            get_network=lambda: self._network,
        )

        self._workers = [rule_updater, alert_reporter, pcap_uploader, heartbeat]
        for w in self._workers:
            w.start()

        self._running = True
        log.info("probe_agent_ready", probe_id=self.probe_id)

    def stop(self) -> None:
        log.info("probe_agent_stopping")
        self._running = False
        for w in self._workers:
            if hasattr(w, "shutdown"):
                w.shutdown()
        self._suricata.stop()
        log.info("probe_agent_stopped")

    def run_forever(self) -> None:
        def _sig_handler(sig, frame):
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT, _sig_handler)

        while self._running:
            time.sleep(5)


def main() -> None:
    agent = ProbeAgent()
    try:
        agent.start()
        agent.run_forever()
    except KeyboardInterrupt:
        agent.stop()
    except Exception as exc:
        log.critical("probe_agent_fatal", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
