"""IDS service: live alert ingestion + per-probe rule catalog and compilation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, delete, func

from app.extensions import db
from app.models.ids import IdsAlert, IdsRule, ProbeRuleAssignment
from app.models.probe import Probe

log = structlog.get_logger(__name__)

_MAX_ALERTS_PER_PROBE = 2000  # ring buffer cap


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
