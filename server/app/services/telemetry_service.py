"""Telemetry ingestion service."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.extensions import db
from app.models.telemetry import DeviceInventory, ServiceInventory, WifiInventory, BLEInventory

log = structlog.get_logger(__name__)


def _merge_details(existing: dict | None, scan: dict) -> dict:
    """Merge new scan info into the stored device details (union of services)."""
    details = dict(existing or {})
    for key in ("hostname", "vendor", "os", "mac", "ip"):
        if scan.get(key):
            details[key] = scan[key]
    # Union of services keyed by port/protocol.
    svc_map = {(s.get("port"), s.get("protocol")): s for s in details.get("services", [])}
    for s in scan.get("services", []) or []:
        svc_map[(s.get("port"), s.get("protocol"))] = s
    if svc_map:
        details["services"] = [svc_map[k] for k in sorted(svc_map, key=lambda x: (x[0] or 0))]
    from datetime import datetime, timezone
    details["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    return details


class TelemetryService:
    def ingest_devices(self, tenant_id: str, probe_id: str, devices: list[dict]) -> list[DeviceInventory]:
        created = []
        for d in devices:
            device = DeviceInventory(
                tenant_id=tenant_id,
                probe_id=probe_id,
                mac=d.get("mac"),
                ip=d.get("ip"),
                hostname=d.get("hostname"),
                vendor=d.get("vendor"),
                device_type=d.get("device_type"),
                os=d.get("os"),
            )
            db.session.add(device)
            created.append(device)
        db.session.commit()
        log.info("devices_ingested", tenant_id=tenant_id, probe_id=probe_id, count=len(created))
        return created

    def upsert_devices(self, tenant_id: str, probe_id: str, devices: list[dict]) -> dict:
        """
        Insert or update devices discovered by a probe, deduplicating on
        (probe_id, mac) or (probe_id, ip). Refreshes last_seen on existing rows
        and records any services found. Returns counts.
        """
        from sqlalchemy import select

        added = updated = 0
        for d in devices:
            mac, ip = d.get("mac"), d.get("ip")
            stmt = select(DeviceInventory).where(DeviceInventory.probe_id == probe_id)
            if mac:
                stmt = stmt.where(DeviceInventory.mac == mac)
            elif ip:
                stmt = stmt.where(DeviceInventory.ip == ip)
            else:
                continue
            device = db.session.execute(stmt).scalars().first()

            now = datetime.now(timezone.utc)
            if device:
                device.last_seen = now
                if ip and not device.ip:
                    device.ip = ip
                if d.get("hostname"):
                    device.hostname = d["hostname"]
                if d.get("vendor"):
                    device.vendor = d["vendor"]
                if d.get("os"):
                    device.os = d["os"]
                device.details = _merge_details(device.details, d)
                updated += 1
            else:
                device = DeviceInventory(
                    tenant_id=tenant_id, probe_id=probe_id,
                    mac=mac, ip=ip,
                    hostname=d.get("hostname"), vendor=d.get("vendor"),
                    device_type=d.get("device_type"), os=d.get("os"),
                    details=_merge_details(None, d),
                )
                db.session.add(device)
                added += 1
            db.session.flush()

            # Presence history: one sighting per detection.
            from app.models.telemetry import DeviceSighting
            db.session.add(DeviceSighting(
                tenant_id=tenant_id, device_id=device.id, probe_id=probe_id, seen_at=now,
            ))

            # Record any open services tied to this device.
            for s in d.get("services", []) or []:
                db.session.add(ServiceInventory(
                    tenant_id=tenant_id, probe_id=probe_id, device_id=device.id,
                    port=s.get("port"), protocol=s.get("protocol"),
                    service=s.get("service"), version=s.get("version"),
                ))

        db.session.commit()
        log.info("devices_upserted", tenant_id=tenant_id, probe_id=probe_id,
                 added=added, updated=updated)
        return {"added": added, "updated": updated}

    def ingest_services(self, tenant_id: str, probe_id: str, services: list[dict]) -> list[ServiceInventory]:
        created = []
        for s in services:
            svc = ServiceInventory(
                tenant_id=tenant_id,
                probe_id=probe_id,
                device_id=s.get("device_id"),
                port=s.get("port"),
                protocol=s.get("protocol"),
                service=s.get("service"),
                version=s.get("version"),
            )
            db.session.add(svc)
            created.append(svc)
        db.session.commit()
        return created

    def ingest_wifi(self, tenant_id: str, probe_id: str, networks: list[dict]) -> list[WifiInventory]:
        created = []
        for n in networks:
            net = WifiInventory(
                tenant_id=tenant_id,
                probe_id=probe_id,
                ssid=n.get("ssid"),
                bssid=n.get("bssid"),
                channel=n.get("channel"),
                encryption=n.get("encryption"),
                signal=n.get("signal"),
            )
            db.session.add(net)
            created.append(net)
        db.session.commit()
        return created

    def ingest_ble(self, tenant_id: str, probe_id: str, devices: list[dict]) -> list[BLEInventory]:
        created = []
        for d in devices:
            ble = BLEInventory(
                tenant_id=tenant_id,
                probe_id=probe_id,
                address=d.get("address"),
                name=d.get("name"),
                manufacturer=d.get("manufacturer"),
                rssi=d.get("rssi"),
            )
            db.session.add(ble)
            created.append(ble)
        db.session.commit()
        return created

    def list_devices(self, tenant_id: str | None, probe_id: str | None = None, limit: int = 100) -> list[DeviceInventory]:
        from sqlalchemy import select
        stmt = select(DeviceInventory)
        if tenant_id is not None:  # None = superadmin, all tenants
            stmt = stmt.where(DeviceInventory.tenant_id == tenant_id)
        if probe_id:
            stmt = stmt.where(DeviceInventory.probe_id == probe_id)
        stmt = stmt.order_by(DeviceInventory.last_seen.desc()).limit(limit)
        return list(db.session.execute(stmt).scalars())

    def get_device(self, device_id: str, tenant_id: str | None = None) -> DeviceInventory | None:
        device = db.session.get(DeviceInventory, device_id)
        if not device:
            return None
        if tenant_id is not None and device.tenant_id != tenant_id:
            return None
        return device

    def list_device_services(self, device_id: str) -> list[ServiceInventory]:
        from sqlalchemy import select
        stmt = select(ServiceInventory).where(ServiceInventory.device_id == device_id).order_by(ServiceInventory.port)
        # Deduplicate by (port, protocol, service, version), keep latest.
        seen, out = set(), []
        for s in db.session.execute(stmt).scalars():
            key = (s.port, s.protocol, s.service, s.version)
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    def list_presence(self, device_id: str, day=None) -> list[dict]:
        """Sightings for a device, optionally limited to a given date (presence history)."""
        from datetime import datetime, timezone, time as _time
        from sqlalchemy import select
        from app.models.telemetry import DeviceSighting
        stmt = select(DeviceSighting).where(DeviceSighting.device_id == device_id)
        if day is not None:
            start = datetime.combine(day, _time.min, tzinfo=timezone.utc)
            end = datetime.combine(day, _time.max, tzinfo=timezone.utc)
            stmt = stmt.where(DeviceSighting.seen_at >= start, DeviceSighting.seen_at <= end)
        stmt = stmt.order_by(DeviceSighting.seen_at.asc()).limit(2000)
        return [s.to_dict() for s in db.session.execute(stmt).scalars()]

    # ── WiFi / BLE listing + upsert ──────────────────────────────────────────

    def list_wifi(self, tenant_id: str | None, probe_id: str | None = None, limit: int = 200) -> list[WifiInventory]:
        from sqlalchemy import select
        stmt = select(WifiInventory)
        if tenant_id is not None:
            stmt = stmt.where(WifiInventory.tenant_id == tenant_id)
        if probe_id:
            stmt = stmt.where(WifiInventory.probe_id == probe_id)
        return list(db.session.execute(stmt.order_by(WifiInventory.seen_at.desc()).limit(limit)).scalars())

    def list_ble(self, tenant_id: str | None, probe_id: str | None = None, limit: int = 200) -> list[BLEInventory]:
        from sqlalchemy import select
        stmt = select(BLEInventory)
        if tenant_id is not None:
            stmt = stmt.where(BLEInventory.tenant_id == tenant_id)
        if probe_id:
            stmt = stmt.where(BLEInventory.probe_id == probe_id)
        return list(db.session.execute(stmt.order_by(BLEInventory.seen_at.desc()).limit(limit)).scalars())

    def upsert_wifi(self, tenant_id: str, probe_id: str, networks: list[dict]) -> dict:
        from sqlalchemy import select
        from datetime import datetime, timezone
        added = updated = 0
        for n in networks:
            bssid = n.get("bssid")
            row = None
            if bssid:
                row = db.session.execute(
                    select(WifiInventory).where(
                        WifiInventory.probe_id == probe_id, WifiInventory.bssid == bssid)
                ).scalars().first()
            if row:
                row.ssid = n.get("ssid") or row.ssid
                row.channel = n.get("channel") if n.get("channel") is not None else row.channel
                row.encryption = n.get("encryption") or row.encryption
                row.signal = n.get("signal") if n.get("signal") is not None else row.signal
                row.seen_at = datetime.now(timezone.utc)
                updated += 1
            else:
                db.session.add(WifiInventory(
                    tenant_id=tenant_id, probe_id=probe_id,
                    ssid=n.get("ssid"), bssid=bssid, channel=n.get("channel"),
                    encryption=n.get("encryption"), signal=n.get("signal"),
                ))
                added += 1
        db.session.commit()
        return {"added": added, "updated": updated}

    def upsert_ble(self, tenant_id: str, probe_id: str, devices: list[dict]) -> dict:
        from sqlalchemy import select
        from datetime import datetime, timezone
        added = updated = 0
        for d in devices:
            addr = d.get("address")
            row = None
            if addr:
                row = db.session.execute(
                    select(BLEInventory).where(
                        BLEInventory.probe_id == probe_id, BLEInventory.address == addr)
                ).scalars().first()
            if row:
                row.name = d.get("name") or row.name
                row.manufacturer = d.get("manufacturer") or row.manufacturer
                row.rssi = d.get("rssi") if d.get("rssi") is not None else row.rssi
                row.seen_at = datetime.now(timezone.utc)
                updated += 1
            else:
                db.session.add(BLEInventory(
                    tenant_id=tenant_id, probe_id=probe_id,
                    address=addr, name=d.get("name"),
                    manufacturer=d.get("manufacturer"), rssi=d.get("rssi"),
                ))
                added += 1
        db.session.commit()
        return {"added": added, "updated": updated}
