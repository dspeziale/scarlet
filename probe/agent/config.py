"""Probe agent configuration — loaded from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class ProbeConfig:
    # ── Server ────────────────────────────────────────────────────────────
    SERVER_URL: str = os.environ["SERVER_URL"].rstrip("/")
    REGISTRATION_TOKEN: str = os.environ.get("REGISTRATION_TOKEN", "")
    AGENT_VERSION: str = os.environ.get("AGENT_VERSION", "1.0.0")

    # ── Identity (populated after registration) ───────────────────────────
    PROBE_ID: str = os.environ.get("PROBE_ID", "")
    PROBE_UUID: str = os.environ.get("PROBE_UUID", "")

    # ── Auth ──────────────────────────────────────────────────────────────
    API_USERNAME: str = os.environ.get("API_USERNAME", "")
    API_PASSWORD: str = os.environ.get("API_PASSWORD", "")

    # ── Intervals (seconds) ───────────────────────────────────────────────
    HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "30"))
    TASK_POLL_INTERVAL: int = int(os.environ.get("TASK_POLL_INTERVAL", "15"))
    RULE_CHECK_INTERVAL: int = int(os.environ.get("RULE_CHECK_INTERVAL", "300"))
    ALERT_FLUSH_INTERVAL: int = int(os.environ.get("ALERT_FLUSH_INTERVAL", "10"))

    # ── Paths ─────────────────────────────────────────────────────────────
    DATA_DIR: Path = Path(os.environ.get("AGENT_DATA_DIR", "/opt/agent/data"))
    STATE_DB: Path = DATA_DIR / "state.db"
    QUEUE_DB: Path = DATA_DIR / "queue.db"
    KEY_FILE: Path = DATA_DIR / "probe_keys.json"
    SURICATA_LOG_DIR: Path = Path(os.environ.get("SURICATA_LOG_DIR", "/var/log/suricata"))
    SURICATA_EVE_LOG: Path = SURICATA_LOG_DIR / "eve.json"
    SURICATA_RULES_PATH: Path = Path("/etc/suricata/rules/probe.rules")
    SURICATA_YAML: Path = Path("/etc/suricata/suricata.yaml")
    SURICATA_YAML_TEMPLATE: Path = Path("/etc/suricata/suricata.yaml.template")
    PCAP_DIR: Path = Path(os.environ.get("PCAP_DIR", "/opt/pcap"))

    # ── IDS defaults ──────────────────────────────────────────────────────
    DEFAULT_INTERFACE: str = os.environ.get("IDS_INTERFACE", "any")
    DEFAULT_CAPTURE_MODE: str = os.environ.get("IDS_CAPTURE_MODE", "af-packet")

    # ── Retry ────────────────────────────────────────────────────────────
    MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", "5"))
    RETRY_BACKOFF_FACTOR: float = float(os.environ.get("RETRY_BACKOFF_FACTOR", "2.0"))

    # ── TLS ──────────────────────────────────────────────────────────────
    VERIFY_TLS: bool = os.environ.get("VERIFY_TLS", "true").lower() == "true"

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.PCAP_DIR.mkdir(parents=True, exist_ok=True)


cfg = ProbeConfig()
