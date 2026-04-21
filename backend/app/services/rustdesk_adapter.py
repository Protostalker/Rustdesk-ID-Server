"""Adapter that maps the live RustDesk OSS schema to our internal device model.

The RustDesk OSS project does not publish a stable schema contract for
``db_v2.sqlite3``. Rather than hardcode column names that may change,
this adapter:

1. Uses :mod:`schema_inspector` to get the live set of tables and columns.
2. Scores each table against a heuristic that rewards RustDesk-ish
   identity and device columns (e.g. ``id`` / ``guid`` + ``hostname`` /
   ``alias`` + ``last_online`` or ``created_at``).
3. Picks the highest-scoring candidate and builds a best-effort mapping
   from live columns to our normalized :class:`DeviceRecord` fields.
4. Reads rows read-only, producing ``DeviceRecord`` objects.

If nothing looks remotely like a peer/device table, the adapter returns
an empty list and records a note. The importer will log it and move on;
the app continues to work for manual device entry.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..schemas import SchemaInspectionReport
from . import schema_inspector

logger = logging.getLogger(__name__)


@dataclass
class DeviceRecord:
    rustdesk_id: str
    hostname: Optional[str] = None
    alias: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    online_status: Optional[str] = None  # "online"|"offline"|None
    raw: Dict = field(default_factory=dict)


# Column-name synonyms we look for. Lowercased. Multiple candidates are
# allowed; the adapter picks the first one that exists in the table.
_ID_CANDIDATES = ["id", "peer_id", "rustdesk_id", "guid", "uuid"]
_HOSTNAME_CANDIDATES = ["hostname", "host_name", "name", "device_name"]
_ALIAS_CANDIDATES = ["alias", "display_name", "note"]
_LAST_SEEN_CANDIDATES = [
    "last_online",
    "last_online_time",
    "last_seen",
    "last_seen_at",
    "updated_at",
    "modified_at",
]
_ONLINE_STATUS_CANDIDATES = ["online", "is_online", "status"]


# Table-level heuristic: names that hint at peers/devices.
_TABLE_NAME_HINTS = ("peer", "device", "client", "rustdesk")


def _pick_first(colnames: List[str], candidates: List[str]) -> Optional[str]:
    cset = {c.lower(): c for c in colnames}
    for cand in candidates:
        if cand in cset:
            return cset[cand]
    return None


def _score_table(table) -> int:
    """Heuristic score: higher means more likely to be the device table."""
    colnames_lc = [c.name.lower() for c in table.columns]
    score = 0
    if any(h in table.name.lower() for h in _TABLE_NAME_HINTS):
        score += 5
    if _pick_first(colnames_lc, _ID_CANDIDATES):
        score += 3
    if _pick_first(colnames_lc, _HOSTNAME_CANDIDATES):
        score += 2
    if _pick_first(colnames_lc, _ALIAS_CANDIDATES):
        score += 1
    if _pick_first(colnames_lc, _LAST_SEEN_CANDIDATES):
        score += 2
    if _pick_first(colnames_lc, _ONLINE_STATUS_CANDIDATES):
        score += 1
    # Bonus for having any rows (empty tables are less interesting).
    if (table.row_count or 0) > 0:
        score += 1
    return score


def _choose_table(report: SchemaInspectionReport):
    if not report.tables:
        return None, {}
    scored = sorted(
        ((t, _score_table(t)) for t in report.tables),
        key=lambda x: x[1],
        reverse=True,
    )
    best, best_score = scored[0]
    # Require a minimum score so we don't pick random tables.
    if best_score < 4:
        return None, {}
    colnames = [c.name for c in best.columns]
    mapping = {
        "id": _pick_first(colnames, _ID_CANDIDATES),
        "hostname": _pick_first(colnames, _HOSTNAME_CANDIDATES),
        "alias": _pick_first(colnames, _ALIAS_CANDIDATES),
        "last_seen": _pick_first(colnames, _LAST_SEEN_CANDIDATES),
        "online_status": _pick_first(colnames, _ONLINE_STATUS_CANDIDATES),
    }
    return best, mapping


def _parse_last_seen(value) -> Optional[datetime]:
    if value is None:
        return None
    # Many RustDesk-ish timestamps are unix seconds. Accept both numeric
    # and ISO string, return UTC-aware datetime.
    try:
        if isinstance(value, (int, float)):
            # Guard against milliseconds
            if value > 1e12:
                value = value / 1000.0
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str):
            # Try unix seconds in string form
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except ValueError:
                pass
            # Try ISO
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    except Exception:
        return None
    return None


def discover(db_path: Path) -> tuple[SchemaInspectionReport, List[DeviceRecord]]:
    """Inspect the RustDesk DB and return normalized device records.

    Returns a tuple: (schema report with chosen table + mapping attached,
    list of DeviceRecord).
    """
    report = schema_inspector.inspect_database(db_path)
    if not report.readable or not report.tables:
        return report, []

    table, mapping = _choose_table(report)
    if table is None or not mapping.get("id"):
        report.notes.append(
            "No table in the RustDesk DB matched the peer/device heuristic. "
            "Manual device management still works. "
            "If RustDesk has changed its schema, update rustdesk_adapter._TABLE_NAME_HINTS "
            "and the *_CANDIDATES column lists."
        )
        logger.warning(
            "No plausible peer/device table found in RustDesk DB at %s", db_path
        )
        return report, []

    report.chosen_table = table.name
    report.column_mapping = mapping
    report.notes.append(
        f"Adapter chose table '{table.name}' using mapping {mapping}. "
        "This is a best-effort guess based on column names."
    )
    logger.info(
        "RustDesk adapter chose table '%s' with mapping %s", table.name, mapping
    )

    # Pull the columns we mapped.
    wanted_cols = [v for v in mapping.values() if v]
    rows = schema_inspector.fetch_rows(db_path, table.name, wanted_cols)

    records: List[DeviceRecord] = []
    for row in rows:
        rid = row.get(mapping["id"]) if mapping["id"] else None
        if rid is None:
            continue
        rid_str = str(rid).strip()
        if not rid_str:
            continue
        online_val = row.get(mapping["online_status"]) if mapping["online_status"] else None
        online_status: Optional[str]
        if online_val is None:
            online_status = None
        elif isinstance(online_val, (int, float)):
            online_status = "online" if int(online_val) != 0 else "offline"
        else:
            s = str(online_val).strip().lower()
            if s in ("1", "true", "online", "yes"):
                online_status = "online"
            elif s in ("0", "false", "offline", "no"):
                online_status = "offline"
            else:
                online_status = None

        records.append(
            DeviceRecord(
                rustdesk_id=rid_str,
                hostname=(row.get(mapping["hostname"]) if mapping["hostname"] else None),
                alias=(row.get(mapping["alias"]) if mapping["alias"] else None),
                last_seen_at=_parse_last_seen(
                    row.get(mapping["last_seen"]) if mapping["last_seen"] else None
                ),
                online_status=online_status,
                raw=row,
            )
        )
    logger.info("Adapter discovered %d RustDesk device records", len(records))
    return report, records


def record_to_raw_json(rec: DeviceRecord) -> str:
    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    return json.dumps(rec.raw, default=_default, ensure_ascii=False)
