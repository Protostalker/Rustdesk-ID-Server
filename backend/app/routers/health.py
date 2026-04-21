from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health():
    settings = get_settings()
    return HealthOut(
        status="ok",
        rustdesk_db_detected=settings.rustdesk_db_path.exists(),
        rustdesk_db_path=str(settings.rustdesk_db_path),
        sync_interval_seconds=settings.sync_interval_seconds,
        launch_rustdesk_enabled=settings.launch_rustdesk_enabled,
    )
