"""
Suricata process lifecycle management.

Reads the template suricata.yaml, replaces %INTERFACE% / %BPF_FILTER%,
writes the live config, then starts/stops/restarts the suricata process.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


class SuricataManager:
    def __init__(
        self,
        yaml_template: Path,
        yaml_live: Path,
        rules_path: Path,
        log_dir: Path,
    ) -> None:
        self._template = yaml_template
        self._yaml = yaml_live
        self._rules = rules_path
        self._log_dir = log_dir
        self._proc: Optional[subprocess.Popen] = None
        self._interface = "any"
        self._bpf = ""
        self._capture_mode = "af-packet"
        self._last_error: Optional[str] = None

    # ── Config ────────────────────────────────────────────────────────────

    def apply_config(
        self,
        interface: str,
        bpf_filter: str = "",
        capture_mode: str = "af-packet",
    ) -> None:
        self._interface = interface or "any"
        self._bpf = bpf_filter or ""
        self._capture_mode = capture_mode or "af-packet"
        self._write_config()
        log.info(
            "suricata_config_applied",
            interface=self._interface,
            capture_mode=self._capture_mode,
        )

    def _write_config(self) -> None:
        if not self._template.exists():
            raise FileNotFoundError(f"Suricata template not found: {self._template}")
        content = self._template.read_text()
        content = content.replace("%INTERFACE%", self._interface)
        content = content.replace("%BPF_FILTER%", self._bpf)
        content = content.replace("%CAPTURE_MODE%", self._capture_mode)
        self._yaml.write_text(content)

    # ── Process ───────────────────────────────────────────────────────────

    def start(self) -> bool:
        if self.is_running():
            log.info("suricata_already_running", pid=self._proc.pid)
            return True
        if not self._yaml.exists():
            self._write_config()
        # The config references a rule file; create an empty one if no ruleset
        # has been deployed yet, so Suricata doesn't fail on a missing file.
        if not self._rules.exists():
            self._rules.parent.mkdir(parents=True, exist_ok=True)
            self._rules.write_text("# no rules deployed yet\n")
            log.info("suricata_empty_ruleset_created", path=str(self._rules))
        cmd = [
            "suricata",
            "-c", str(self._yaml),
            "--pidfile", "/var/run/suricata.pid",
            "-D",          # daemonise
            "-v",
        ]
        log.info("suricata_start", cmd=" ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            time.sleep(2)
            if self._proc.poll() is not None:
                err = self._proc.stderr.read().decode(errors="replace")
                self._last_error = err.strip()[-1000:] or f"exited with code {self._proc.returncode}"
                log.error("suricata_start_failed", returncode=self._proc.returncode, stderr=err)
                return False
            self._last_error = None
            log.info("suricata_started", pid=self._proc.pid)
            return True
        except FileNotFoundError:
            self._last_error = "suricata binary not found"
            log.error("suricata_binary_not_found")
            return False

    def stop(self, timeout: int = 10) -> None:
        pid = self._pid_from_file()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                _wait_for_pid(pid, timeout)
                log.info("suricata_stopped_via_pidfile", pid=pid)
                return
            except ProcessLookupError:
                pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            log.info("suricata_stopped", pid=self._proc.pid)
        self._proc = None

    def restart(self) -> bool:
        self.stop()
        time.sleep(1)
        return self.start()

    def reload_rules(self) -> None:
        """Send SIGUSR2 to make Suricata reload rules without restart."""
        pid = self._pid_from_file() or (self._proc.pid if self._proc else None)
        if pid:
            os.kill(pid, signal.SIGUSR2)
            log.info("suricata_rules_reload_signal_sent", pid=pid)
        else:
            log.warning("suricata_reload_no_pid")

    def is_running(self) -> bool:
        pid = self._pid_from_file()
        if pid:
            try:
                os.kill(pid, 0)
                return True
            except (ProcessLookupError, PermissionError):
                pass
        if self._proc:
            return self._proc.poll() is None
        return False

    def status(self) -> dict:
        running = self.is_running()
        pid = self._pid_from_file() if running else None
        version = _get_version()
        return {
            "running": running,
            "pid": pid,
            "version": version,
            "interface": self._interface,
            "capture_mode": self._capture_mode,
        }

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _pid_from_file(self) -> Optional[int]:
        pid_path = Path("/var/run/suricata.pid")
        if pid_path.exists():
            try:
                return int(pid_path.read_text().strip())
            except ValueError:
                pass
        return None


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_version() -> str:
    try:
        result = subprocess.run(
            ["suricata", "--build-info"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"Version\s+([\d.]+)", result.stdout)
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


def _wait_for_pid(pid: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.25)
