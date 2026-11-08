"""Lease data access and date logic, shared by the CLI (main.py) and the API (api.py)."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from seed_db import DEFAULT_DB_PATH, JSON_SEED, LEASE_COLUMNS

# Public seed source. load_leases() reads SQLite, not this file.
DATA_FILE = JSON_SEED
SELECT_LEASES = "SELECT " + ", ".join(LEASE_COLUMNS) + " FROM leases"


def resolve_db_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("LEASES_DB")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def _connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database, or fail clearly if it has not been seeded.

    sqlite3.connect() silently creates an empty file when the path is missing,
    which then fails later with "no such table". Check first so nothing is created.
    """
    db_path = resolve_db_path(path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}. Build it with: python seed_db.py")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def lease_status(expires: str, today: date) -> str:
    """'expired' once the expiry date is before today; a lease expiring today is still 'active'.

    Worked out on every read, never stored, so it cannot go stale. This matches the window
    rules below: a lease expiring today is inside "the next N days" and is not yet expired.
    """
    return "expired" if date.fromisoformat(expires) < today else "active"


def _row_to_dict(row: sqlite3.Row, today: date) -> dict:
    lease = {column: row[column] for column in LEASE_COLUMNS}
    lease["status"] = lease_status(lease["expires"], today)
    return lease


def load_leases(
    path: Path | None = None,
    status: str | None = None,
    property_type: str | None = None,
    today: date | None = None,
) -> list[dict]:
    """Return lease rows from SQLite, each with a `status` worked out for `today`.

    `status` ('active' or 'expired') and `property_type` are applied with parameterised SQL.
    `today` defaults to the real date; pass one to get repeatable results.
    `path` is the database file; it defaults to $LEASES_DB or data/leases.db.
    """
    today = today or date.today()
    clauses: list[str] = []
    params: list[str] = []
    if status is not None:
        if status not in ("active", "expired"):
            raise ValueError(f"status must be 'active' or 'expired', got {status!r}")
        clauses.append("expires < ?" if status == "expired" else "expires >= ?")
        params.append(today.isoformat())
    if property_type is not None:
        clauses.append("property_type = ?")
        params.append(property_type)

    sql = SELECT_LEASES
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    with closing(_connect(path)) as conn:
        return [_row_to_dict(row, today) for row in conn.execute(sql, params)]


def get_lease_by_id(lease_id: str, path: Path | None = None, today: date | None = None) -> dict | None:
    today = today or date.today()
    sql = SELECT_LEASES + " WHERE lease_id = ?"
    with closing(_connect(path)) as conn:
        row = conn.execute(sql, (lease_id,)).fetchone()
    return _row_to_dict(row, today) if row else None


def leases_expiring_within(leases: list[dict], today: date, days: int) -> list[dict]:
    """Ground truth for 'expires in the next N days', computed in code, not by the model.

    The window is inclusive at both ends: a lease expiring today or exactly `days` days out counts.
    """
    end = today + timedelta(days=days)
    return [
        lease
        for lease in leases
        if today <= datetime.strptime(lease["expires"], "%Y-%m-%d").date() <= end
    ]


def query_expiring_leases(today: date, days: int, path: Path | None = None) -> list[dict]:
    """Leases whose expiry falls in [today, today + days], compared in SQL."""
    end = today + timedelta(days=days)
    sql = SELECT_LEASES + " WHERE expires >= ? AND expires <= ? ORDER BY expires ASC"
    with closing(_connect(path)) as conn:
        rows = conn.execute(sql, (today.isoformat(), end.isoformat()))
        return [_row_to_dict(row, today) for row in rows]
