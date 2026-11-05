"""Lease data access and date logic, shared by the CLI (main.py) and the API (api.py)."""

from __future__ import annotations

import os
import sqlite3
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
    conn = sqlite3.connect(resolve_db_path(path))
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {column: row[column] for column in LEASE_COLUMNS}


def load_leases(
    path: Path | None = None,
    status: str | None = None,
    property_type: str | None = None,
) -> list[dict]:
    """Return lease rows from SQLite.

    Optional `status` and `property_type` are applied with parameterised SQL.
    `path` is the database file; it defaults to $LEASES_DB or data/leases.db.
    """
    clauses: list[str] = []
    params: list[str] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if property_type is not None:
        clauses.append("property_type = ?")
        params.append(property_type)

    sql = SELECT_LEASES
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    with _connect(path) as conn:
        return [_row_to_dict(row) for row in conn.execute(sql, params)]


def get_lease_by_id(lease_id: str, path: Path | None = None) -> dict | None:
    sql = SELECT_LEASES + " WHERE lease_id = ?"
    with _connect(path) as conn:
        row = conn.execute(sql, (lease_id,)).fetchone()
    return _row_to_dict(row) if row else None


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
    with _connect(path) as conn:
        rows = conn.execute(sql, (today.isoformat(), end.isoformat()))
        return [_row_to_dict(row) for row in rows]
