"""Background loop that polls hbbs for peer liveness and writes the current
state into the app DB (Device.online_status + Device.last_seen_at).

No history logging — current state only, overwritten each tick. If you ever
want an audit trail, add a PresenceEvent table and record here.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import Device
from .hbbs_presence import query_presence

logger = logging.getLogger(__name__)


class PresenceScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._trigger = asyncio.Event()
        self._last_ok: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._last_online_count: int = 0
        self._last_queried_count: int = 0

    # ---------- lifecycle ----------

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        settings = get_settings()
        if not settings.hbbs_host or not settings.hbbs_port:
            logger.info(
                "Presence scheduler disabled (hbbs_host/hbbs_port not set)"
            )
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="hbbs-presence-loop")
        logger.info(
            "Presence scheduler started host=%s port=%s interval=%ss",
            settings.hbbs_host,
            settings.hbbs_port,
            settings.presence_interval_seconds,
        )

    async def stop(self) -> None:
        self._stop.set()
        self._trigger.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        logger.info("Presence scheduler stopped")

    def trigger_now(self) -> None:
        self._trigger.set()

    # ---------- status exposed to the API ----------

    def status(self) -> dict:
        settings = get_settings()
        return {
            "enabled": self._task is not None and not self._task.done(),
            "host": settings.hbbs_host,
            "port": settings.hbbs_port,
            "interval_seconds": settings.presence_interval_seconds,
            "last_ok_at": self._last_ok.isoformat() if self._last_ok else None,
            "last_error": self._last_error,
            "last_online_count": self._last_online_count,
            "last_queried_count": self._last_queried_count,
        }

    # ---------- internals ----------

    async def _run(self) -> None:
        settings = get_settings()
        interval = max(5, settings.presence_interval_seconds)
        # fire once right away
        await self._safe_cycle()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._trigger.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self._trigger.clear()
            if self._stop.is_set():
                break
            await self._safe_cycle()

    async def _safe_cycle(self) -> None:
        try:
            await asyncio.to_thread(self._poll_and_persist)
        except Exception:
            logger.exception("Unhandled error in presence cycle")

    def _poll_and_persist(self) -> None:
        settings = get_settings()
        host = settings.hbbs_host
        port = settings.hbbs_port
        if not host or not port:
            return

        session: Session = SessionLocal()
        try:
            rows = session.execute(
                select(Device.id, Device.rustdesk_id).where(
                    Device.rustdesk_id.is_not(None)
                )
            ).all()
            id_by_peer = {pid: dev_id for (dev_id, pid) in rows if pid}
            peer_ids = list(id_by_peer.keys())

            if not peer_ids:
                self._last_queried_count = 0
                self._last_online_count = 0
                self._last_ok = datetime.now(timezone.utc)
                self._last_error = None
                return

            try:
                result = query_presence(
                    host,
                    int(port),
                    peer_ids,
                    requester_id="rdac",
                    timeout_s=float(settings.presence_timeout_seconds),
                )
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "hbbs presence query failed: %s (devices=%d)",
                    self._last_error,
                    len(peer_ids),
                )
                return

            now = datetime.now(timezone.utc)
            online_count = 0
            for pid, dev_id in id_by_peer.items():
                is_online = result.is_online(pid)
                dev = session.get(Device, dev_id)
                if dev is None:
                    continue
                dev.online_status = "online" if is_online else "offline"
                if is_online:
                    dev.last_seen_at = now
                    online_count += 1
            session.commit()

            self._last_queried_count = len(peer_ids)
            self._last_online_count = online_count
            self._last_ok = now
            self._last_error = None
            logger.info(
                "Presence tick: %d / %d online", online_count, len(peer_ids)
            )
        finally:
            session.close()


# Module-level singleton — mirrors sync_scheduler.scheduler pattern.
presence_scheduler = PresenceScheduler()
