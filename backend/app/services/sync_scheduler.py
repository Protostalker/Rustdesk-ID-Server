"""Simple asyncio background scheduler for the RustDesk -> app DB sync."""
from __future__ import annotations

import asyncio
import logging

from ..config import get_settings
from . import importer

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._trigger = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="rustdesk-sync-loop")
        logger.info("Sync scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        self._trigger.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        logger.info("Sync scheduler stopped")

    def trigger_now(self) -> None:
        """Ask the loop to run an immediate cycle without waiting for the tick."""
        self._trigger.set()

    async def _run(self) -> None:
        interval = max(5, get_settings().sync_interval_seconds)
        # Always run once at startup.
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
            # importer is synchronous + uses SQLAlchemy; run in a worker thread
            # so we never block the event loop.
            await asyncio.to_thread(importer.run_sync_once)
        except Exception:
            logger.exception("Unhandled error in sync cycle")


scheduler = SyncScheduler()
