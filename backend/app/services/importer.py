"""Sync loop: read from RustDesk (via adapter) -> upsert into app DB.

Admin-owned metadata is preserved on every cycle:
 - nickname
 - notes
 - company assignments (via ``device_company_assignments``)
 - source_type of a manually-created device is never downgraded

Only fields derived from RustDesk are updated during import:
 - hostname
 - alias_from_rustdesk
 - last_seen_at
 - online_status
 - rustdesk_raw_payload_json
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import Device, SyncRun
from . import rustdesk_adapter
from .rustdesk_adapter import DeviceRecord

logger = logging.getLogger(__name__)


_last_schema_report = None


def get_last_schema_report():
    return _last_schema_report


def run_sync_once() -> SyncRun:
    """Run one full sync cycle. Returns the persisted SyncRun row."""
    global _last_schema_report
    settings = get_settings()
    db: Session = SessionLocal()
    run = SyncRun(started_at=datetime.now(timezone.utc), status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        db_path = settings.rustdesk_db_path
        if not db_path.exists():
            run.status = "skipped"
            run.message = (
                f"RustDesk DB not found at {db_path}. "
                "The app is still fully usable for manual device management."
            )
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.warning(run.message)
            return run

        report, records = rustdesk_adapter.discover(db_path)
        _last_schema_report = report

        if not records:
            run.status = "success"
            run.message = (
                "RustDesk DB was readable but no device rows were produced. "
                f"Notes: {'; '.join(report.notes) if report.notes else 'none'}"
            )
            run.devices_seen = 0
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return run

        inserted, updated = _upsert_records(db, records)
        run.devices_seen = len(records)
        run.devices_inserted = inserted
        run.devices_updated = updated
        run.status = "success"
        run.message = (
            f"Synced {len(records)} devices "
            f"(inserted={inserted}, updated={updated}) "
            f"from table '{report.chosen_table}'."
        )
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(run.message)
        return run
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        run.status = "error"
        run.message = f"Sync failed: {exc}"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception("Sync failed")
        return run
    finally:
        db.close()


def _upsert_records(db: Session, records: list[DeviceRecord]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for rec in records:
        existing: Optional[Device] = db.execute(
            select(Device).where(Device.rustdesk_id == rec.rustdesk_id)
        ).scalar_one_or_none()

        raw_json = rustdesk_adapter.record_to_raw_json(rec)

        if existing is None:
            d = Device(
                rustdesk_id=rec.rustdesk_id,
                hostname=rec.hostname,
                alias_from_rustdesk=rec.alias,
                last_seen_at=rec.last_seen_at,
                online_status=rec.online_status,
                source_type="imported",
                rustdesk_raw_payload_json=raw_json,
            )
            db.add(d)
            inserted += 1
        else:
            # Preserve admin metadata. Only refresh RustDesk-derived fields.
            existing.hostname = rec.hostname or existing.hostname
            existing.alias_from_rustdesk = rec.alias
            existing.last_seen_at = rec.last_seen_at or existing.last_seen_at
            existing.online_status = rec.online_status
            existing.rustdesk_raw_payload_json = raw_json
            # Never downgrade a manual device; do not touch source_type
            # unless it is unset (safety).
            if not existing.source_type:
                existing.source_type = "imported"
            updated += 1
    db.commit()
    return inserted, updated
