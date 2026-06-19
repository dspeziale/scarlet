"""Telemetry ingestion service."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.extensions import db
from app.models.telemetry import DeviceInventory, ServiceInventory, WifiInventory, BLEInventory

log = structlog.get_logger(__name__)


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

            if device:
                device.last_seen = datetime.now(timezone.utc)
                if ip and not device.ip:
                    device.ip = ip
                if d.get("hostname"):
                    device.hostname = d["hostname"]
                if d.get("vendor"):
                    device.vendor = d["vendor"]
                if d.get("os"):
                    device.os = d["os"]
                updated += 1
            else:
                device = DeviceInventory(
                    tenant_id=tenant_id, probe_id=probe_id,
                    mac=mac, ip=ip,
                    hostname=d.get("hostname"), vendor=d.get("vendor"),
                    device_type=d.get("device_type"), os=d.get("os"),
                )
                db.session.add(device)
                added += 1
            db.session.flush()

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

    def list_devices(self, tenant_id: str, probe_id: str | None = None, limit: int = 100) -> list[DeviceInventory]:
        from sqlalchemy import select
        stmt = select(DeviceInventory).where(DeviceInventory.tenant_id == tenant_id)
        if probe_id:
            stmt = stmt.where(DeviceInventory.probe_id == probe_id)
        stmt = stmt.order_by(DeviceInventory.last_seen.desc()).limit(limit)
        return list(db.session.execute(stmt).scalars())
