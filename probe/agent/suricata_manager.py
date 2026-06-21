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
        # Kill any orphan instance + stale pidfile (avoids cluster-id conflicts
        # and Suricata refusing to start).
        self._cleanup_stale()

        # Run Suricata in the FOREGROUND and manage it as our child process.
        # (Daemon mode -D forks and the parent exits 0 immediately, which makes
        # success/failure detection unreliable. In a container the daemon would
        # die with the agent anyway, so foreground is both simpler and robust.)
        cmd = [
            "suricata",
            "-c", str(self._yaml),
            "--pidfile", "/var/run/suricata.pid",
            "-v",
        ]
        # Suricata 8 requires an explicit capture-mode flag on the command line.
        iface = self._interface or "any"
        if self._capture_mode == "pcap":
            cmd += ["--pcap" if iface == "any" else f"--pcap={iface}"]
        else:  # af-packet (default)
            cmd += ["--af-packet" if iface == "any" else f"--af-packet={iface}"]
        log.info("suricata_start", cmd=" ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._last_error = "suricata binary not found"
            log.error("suricata_binary_not_found")
            return False

        # A bad config/interface makes Suricata exit within a couple of seconds;
        # a healthy engine keeps running. Wait out a short grace period.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                self._last_error = (self._log_tail() or
                                    f"exited with code {self._proc.returncode}")[-1500:]
                log.error("suricata_start_failed", returncode=self._proc.returncode,
                          log_tail=self._last_error)
                return False
            time.sleep(0.5)
        self._last_error = None
        log.info("suricata_started", pid=self._proc.pid)
        return True

    def _cleanup_stale(self) -> None:
        """Kill any leftover suricata process and remove a stale pidfile."""
        pid = self._pid_from_file()
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        pid_path = Path("/var/run/suricata.pid")
        if pid_path.exists():
            try:
                pid_path.unlink()
            except OSError:
                pass

    def stop(self, timeout: int = 10) -> None:
        # Foreground child we manage.
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        self._proc = None
        # Belt and suspenders: terminate any pid still in the pidfile.
        pid = self._pid_from_file()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                _wait_for_pid(pid, timeout)
            except ProcessLookupError:
                pass
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            Path("/var/run/suricata.pid").unlink(missing_ok=True)
        except OSError:
            pass
        log.info("suricata_stopped")

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
        # Primary: our foreground child.
        if self._proc is not None:
            return self._proc.poll() is None
        # Fallback: a pid from the pidfile (e.g., leftover from a prior run).
        pid = self._pid_from_file()
        if pid:
            try:
                os.kill(pid, 0)
                return True
            except PermissionError:
                return True
            except ProcessLookupError:
                return False
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

    def _log_tail(self, max_lines: int = 15) -> str:
        """Return the last error/warning lines from suricata.log (if present)."""
        log_path = self._log_dir / "suricata.log"
        try:
            lines = log_path.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        # Prefer error/warning lines; fall back to the raw tail.
        relevant = [ln for ln in lines if "Error" in ln or "Warning" in ln]
        chosen = (relevant or lines)[-max_lines:]
        return "\n".join(chosen).strip()

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
