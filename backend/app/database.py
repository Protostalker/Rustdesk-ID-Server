"""Application database engine + session factory.

This is the *companion* database. It is never the RustDesk DB.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Ensure parent directory exists. Inside the container this is /data.
db_path = Path(settings.app_db_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{db_path}",
    echo=False,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _connection_record):
    # Enforce foreign keys for referential integrity.
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables and the max-two-companies trigger."""
    from . import models  # noqa: F401  (ensures model registration)

    Base.metadata.create_all(bind=engine)

    # Database-level safeguard for the "max 2 companies per device" rule.
    # The application layer also enforces this, but this trigger stops
    # a bug or direct DB write from breaking the invariant.
    trigger_sql = """
    CREATE TRIGGER IF NOT EXISTS trg_max_two_companies_per_device
    BEFORE INSERT ON device_company_assignments
    FOR EACH ROW
    WHEN (
        SELECT COUNT(*)
        FROM device_company_assignments
        WHERE device_id = NEW.device_id
    ) >= 2
    BEGIN
        SELECT RAISE(ABORT, 'max 2 companies per device');
    END;
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(trigger_sql)
    logger.info("Application database initialized at %s", db_path)
