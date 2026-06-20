"""IDS service: live alert ingestion + per-probe rule catalog and compilation."""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, delete, func

from app.extensions import db
from app.models.ids import IdsAlert, IdsRule, ProbeRuleAssignment
from app.models.probe import Probe

log = structlog.get_logger(__name__)

_MAX_ALERTS_PER_PROBE = 2000  # ring buffer cap


_RULE_ACTIONS = ("alert", "drop", "reject", "pass", "sdrop", "log")
_SID_RE = re.compile(r"\bsid:\s*(\d+)")
_MSG_RE = re.compile(r'\bmsg:\s*"([^"]*)"')
_CLASS_RE = re.compile(r"\bclasstype:\s*([\w-]+)")


def parse_rule_lines(content: str) -> list[dict]:
    """Parse a Suricata .rules file into rule dicts (rule_text, sid, msg, category)."""
    rules: list[dict] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        first = line.split(None, 1)[0].lower()
        if first not in _RULE_ACTIONS or "sid:" not in line:
            continue
        sid_m = _SID_RE.search(line)
        msg_m = _MSG_RE.search(line)
        cls_m = _CLASS_RE.search(line)
        rules.append({
            "rule_text": line,
            "sid": int(sid_m.group(1)) if sid_m else None,
            "msg": msg_m.group(1) if msg_m else None,
            "category": cls_m.group(1) if cls_m else None,
        })
    return rules


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class IdsService:
    # ── Alerts ───────────────────────────────────────────────────────────────

    def ingest_alerts(self, tenant_id: str, probe_id: str, events: list[dict]) -> int:
        count = 0
        for ev in events:
            alert = ev.get("alert", {}) if isinstance(ev, dict) else {}
            db.session.add(IdsAlert(
                tenant_id=tenant_id,
                probe_id=probe_id,
                event_time=_parse_ts(ev.get("timestamp")),
                signature=alert.get("signature") or ev.get("signature"),
                category=alert.get("category"),
                severity=alert.get("severity"),
                src_ip=ev.get("src_ip"),
                src_port=ev.get("src_port"),
                dest_ip=ev.get("dest_ip"),
                dest_port=ev.get("dest_port"),
                protocol=ev.get("proto"),
                raw=ev,
            ))
            count += 1
        db.session.commit()
        self._trim_alerts(probe_id)
        log.info("ids_alerts_ingested", probe_id=probe_id, count=count)
        return count

    def _trim_alerts(self, probe_id: str) -> None:
        total = db.session.execute(
            select(func.count(IdsAlert.id)).where(IdsAlert.probe_id == probe_id)
        ).scalar_one()
        if total <= _MAX_ALERTS_PER_PROBE:
            return
        # delete the oldest overflow
        overflow = total - _MAX_ALERTS_PER_PROBE
        old_ids = db.session.execute(
            select(IdsAlert.id).where(IdsAlert.probe_id == probe_id)
            .order_by(IdsAlert.id.asc()).limit(overflow)
        ).scalars().all()
        if old_ids:
            db.session.execute(delete(IdsAlert).where(IdsAlert.id.in_(old_ids)))
            db.session.commit()

    def list_alerts(self, tenant_id: str, probe_id: str, since_id: int = 0, limit: int = 200) -> list[IdsAlert]:
        stmt = select(IdsAlert).where(
            IdsAlert.tenant_id == tenant_id,
            IdsAlert.probe_id == probe_id,
            IdsAlert.id > since_id,
        ).order_by(IdsAlert.id.asc()).limit(limit)
        return list(db.session.execute(stmt).scalars())

    # ── Rule catalog ─────────────────────────────────────────────────────────

    def list_rules(self, tenant_id: str) -> list[IdsRule]:
        stmt = select(IdsRule).where(IdsRule.tenant_id == tenant_id).order_by(IdsRule.created_at.desc())
        return list(db.session.execute(stmt).scalars())

    def create_rule(self, tenant_id: str, rule_text: str, msg: str | None = None,
                    sid: int | None = None, category: str | None = None) -> IdsRule:
        rule = IdsRule(tenant_id=tenant_id, rule_text=rule_text.strip(),
                       msg=msg, sid=sid, category=category)
        db.session.add(rule)
        db.session.commit()
        return rule

    def import_rules_from_url(self, tenant_id: str, url: str, max_rules: int = 5000) -> dict:
        """
        Download a Suricata .rules file from an http(s) URL and add its rules to
        the tenant catalog. Skips rules whose sid already exists. Returns counts.
        """
        if not re.match(r"^https?://", url, re.IGNORECASE):
            raise ValueError("URL must start with http:// or https://")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SOC-Seattle/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, ValueError) as exc:
            raise ValueError(f"download failed: {exc}") from exc

        parsed = parse_rule_lines(content)
        if not parsed:
            return {"added": 0, "skipped": 0, "total": 0}

        existing_sids = {
            s for (s,) in db.session.execute(
                select(IdsRule.sid).where(IdsRule.tenant_id == tenant_id, IdsRule.sid.isnot(None))
            ).all()
        }
        added = skipped = 0
        for r in parsed[:max_rules]:
            if r["sid"] is not None and r["sid"] in existing_sids:
                skipped += 1
                continue
            db.session.add(IdsRule(
                tenant_id=tenant_id, rule_text=r["rule_text"],
                msg=r["msg"], sid=r["sid"], category=r["category"], enabled=True,
            ))
            if r["sid"] is not None:
                existing_sids.add(r["sid"])
            added += 1
        db.session.commit()
        log.info("rules_imported", tenant_id=tenant_id, url=url, added=added, skipped=skipped)
        return {"added": added, "skipped": skipped, "total": len(parsed)}

    def delete_rule(self, tenant_id: str, rule_id: str) -> None:
        rule = db.session.get(IdsRule, rule_id)
        if not rule or rule.tenant_id != tenant_id:
            raise ValueError("Rule not found")
        db.session.execute(delete(ProbeRuleAssignment).where(ProbeRuleAssignment.rule_id == rule_id))
        db.session.delete(rule)
        db.session.commit()

    # ── Per-probe assignment ────────────────────────────────────────────────

    def get_probe_rule_ids(self, probe_id: str) -> set[str]:
        rows = db.session.execute(
            select(ProbeRuleAssignment.rule_id).where(
                ProbeRuleAssignment.probe_id == probe_id,
                ProbeRuleAssignment.active == True,  # noqa: E712
            )
        ).scalars().all()
        return set(rows)

    def set_probe_rules(self, tenant_id: str, probe_id: str, rule_ids: list[str]) -> str:
        """Replace the active rule set for a probe. Returns the new version."""
        db.session.execute(delete(ProbeRuleAssignment).where(ProbeRuleAssignment.probe_id == probe_id))
        for rid in set(rule_ids):
            db.session.add(ProbeRuleAssignment(
                tenant_id=tenant_id, probe_id=probe_id, rule_id=rid, active=True,
            ))
        version = self._compute_version(tenant_id, rule_ids)
        probe = db.session.get(Probe, probe_id)
        if probe:
            probe.ruleset_version = version
        db.session.commit()
        log.info("probe_rules_set", probe_id=probe_id, count=len(set(rule_ids)), version=version)
        return version

    def compile_rules_for_probe(self, tenant_id: str, probe_id: str) -> tuple[str, str]:
        """Return (rules_text, version) for the probe's active+enabled rules."""
        rule_ids = self.get_probe_rule_ids(probe_id)
        if not rule_ids:
            return "", self._compute_version(tenant_id, [])
        stmt = select(IdsRule).where(
            IdsRule.id.in_(rule_ids),
            IdsRule.tenant_id == tenant_id,
            IdsRule.enabled == True,  # noqa: E712
        ).order_by(IdsRule.created_at.asc())
        rules = list(db.session.execute(stmt).scalars())
        text = "\n".join(r.rule_text.strip() for r in rules) + ("\n" if rules else "")
        version = self._compute_version(tenant_id, [r.id for r in rules])
        return text, version

    def _compute_version(self, tenant_id: str, rule_ids: list[str]) -> str:
        h = hashlib.sha256()
        for rid in sorted(set(rule_ids)):
            h.update(rid.encode())
        return h.hexdigest()[:16] if rule_ids else "empty"
