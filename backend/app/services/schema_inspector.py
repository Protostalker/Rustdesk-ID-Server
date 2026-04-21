"""Read-only inspection of the RustDesk OSS SQLite database.

RustDesk OSS ships with a SQLite database whose internal schema is not a
stable public API. This module makes no assumptions: it opens the file
strictly read-only, enumerates tables and columns, and hands the raw
picture to the adapter for mapping.

Read-only is enforced with a SQLite URI ``mode=ro``. No writes are ever
issued. Transactions are not used.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..schemas import (
    SchemaInspectionColumn,
    SchemaInspectionReport,
    SchemaInspectionTable,
)

logger = logging.getLogger(__name__)


@dataclass
class RawTable:
    name: str
    columns: List[dict] = field(default_factory=list)
    row_count: Optional[int] = None


def _ro_connect(path: Path) -> sqlite3.Connection:
    """Open the RustDesk DB strictly read-only via SQLite URI.

    Using ``mode=ro`` means the SQLite library itself will refuse any
    write, even if our code tried. The adapter layer relies on this.
    """
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def inspect_database(db_path: Path) -> SchemaInspectionReport:
    """Return a full picture of the RustDesk DB without modifying it."""
    report = SchemaInspectionReport(
        db_path=str(db_path),
        db_exists=db_path.exists(),
        readable=False,
    )
    if not db_path.exists():
        report.notes.append(
            f"RustDesk DB not found at {db_path}. Manual device management still works."
        )
        logger.warning("RustDesk DB not found at %s", db_path)
        return report

    try:
        conn = _ro_connect(db_path)
    except sqlite3.Error as exc:
        report.notes.append(f"Could not open RustDesk DB read-only: {exc}")
        logger.exception("Failed to open RustDesk DB read-only")
        return report

    try:
        report.readable = True
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        table_names = [r["name"] for r in cur.fetchall()]
        logger.info("RustDesk DB tables discovered: %s", table_names)

        tables: List[SchemaInspectionTable] = []
        for tname in table_names:
            # PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk)
            cur.execute(f"PRAGMA table_info('{tname}')")
            cols = [
                SchemaInspectionColumn(
                    name=row["name"],
                    type=(row["type"] or "").upper(),
                    notnull=bool(row["notnull"]),
                    pk=bool(row["pk"]),
                )
                for row in cur.fetchall()
            ]
            row_count: Optional[int] = None
            try:
                cur.execute(f"SELECT COUNT(*) AS c FROM '{tname}'")
                row_count = int(cur.fetchone()["c"])
            except sqlite3.Error as exc:
                logger.debug("Could not count rows for %s: %s", tname, exc)
            tables.append(
                SchemaInspectionTable(name=tname, columns=cols, row_count=row_count)
            )
        report.tables = tables
    finally:
        conn.close()

    return report


def fetch_rows(db_path: Path, table: str, columns: List[str], limit: int = 50000):
    """Read-only fetch of rows for a specific table/column set.

    Table and column names are validated against the live schema before
    being interpolated, because SQLite does not allow parameterized
    identifiers.
    """
    with _ro_connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info('{table}')")
        valid_cols = {row["name"] for row in cur.fetchall()}
        safe_cols = [c for c in columns if c in valid_cols]
        if not safe_cols:
            return []
        col_sql = ", ".join(f'"{c}"' for c in safe_cols)
        cur.execute(f'SELECT {col_sql} FROM "{table}" LIMIT {int(limit)}')
        rows = cur.fetchall()
        return [dict(r) for r in rows]
