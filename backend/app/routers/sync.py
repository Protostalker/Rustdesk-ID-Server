from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import SyncRun
from ..schemas import SchemaInspectionReport, SyncRunOut, SyncStatus
from ..services import importer, schema_inspector
from ..services.presence_scheduler import presence_scheduler
from ..services.sync_scheduler import scheduler

router = APIRouter(prefix="/sync", tags=["sync"])


def _run_to_out(run: SyncRun) -> SyncRunOut:
    return SyncRunOut(
        id=run.id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        message=run.message,
        devices_seen=run.devices_seen,
        devices_inserted=run.devices_inserted,
        devices_updated=run.devices_updated,
    )


@router.get("/status", response_model=SyncStatus)
def get_status(db: Session = Depends(get_db)):
    settings = get_settings()
    recent = (
        db.execute(select(SyncRun).order_by(SyncRun.id.desc()).limit(20))
        .scalars()
        .all()
    )
    last = recent[0] if recent else None

    report: SchemaInspectionReport | None = importer.get_last_schema_report()
    if report is None:
        # Provide an on-demand snapshot even if the scheduler hasn't run yet.
        report = schema_inspector.inspect_database(settings.rustdesk_db_path)

    return SyncStatus(
        interval_seconds=settings.sync_interval_seconds,
        last_run=_run_to_out(last) if last else None,
        recent_runs=[_run_to_out(r) for r in recent],
        schema_report=report,
        launch_rustdesk_enabled=settings.launch_rustdesk_enabled,
    )


@router.post("/trigger", response_model=SyncStatus)
def trigger_sync(db: Session = Depends(get_db)):
    scheduler.trigger_now()
    return get_status(db)


@router.get("/schema", response_model=SchemaInspectionReport)
def inspect_schema_now():
    settings = get_settings()
    return schema_inspector.inspect_database(settings.rustdesk_db_path)


@router.get("/presence/status")
def presence_status():
    """Current state of the hbbs presence poller (host/port, last tick, counts)."""
    return presence_scheduler.status()


@router.post("/presence/run")
def presence_run_now():
    """Kick an immediate presence poll without waiting for the interval."""
    presence_scheduler.trigger_now()
    return presence_scheduler.status()
