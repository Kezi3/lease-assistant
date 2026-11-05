"""Create the SQLite leases table from data/leases.json.

Safe to run more than once: the table is dropped and rebuilt so the database
matches the JSON seed exactly.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

JSON_SEED = Path(__file__).parent / "data" / "leases.json"
DEFAULT_DB_PATH = Path(__file__).parent / "data" / "leases.db"

LEASE_COLUMNS = (
    "lease_id",
    "property",
    "tenant",
    "expires",
    "rent_ngn",
    "property_type",
    "status",
)

CREATE_TABLE_SQL = """
CREATE TABLE leases (
    lease_id TEXT PRIMARY KEY,
    property TEXT NOT NULL,
    tenant TEXT NOT NULL,
    expires TEXT NOT NULL,
    rent_ngn INTEGER NOT NULL,
    property_type TEXT NOT NULL,
    status TEXT NOT NULL
)
"""

INSERT_SQL = """
INSERT INTO leases (
    lease_id, property, tenant, expires, rent_ngn, property_type, status
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def seed(db_path: Path | None = None, json_path: Path | None = None) -> Path:
    """Create the leases table and load every row from the JSON seed.

    Recreates the table on each run so a second call cannot leave stale rows.
    """
    db_path = Path(db_path or DEFAULT_DB_PATH)
    json_path = Path(json_path or JSON_SEED)
    rows = json.loads(json_path.read_text())
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS leases")
        conn.execute(CREATE_TABLE_SQL)
        conn.executemany(
            INSERT_SQL,
            [tuple(row[column] for column in LEASE_COLUMNS) for row in rows],
        )
        conn.commit()
    return db_path


if __name__ == "__main__":
    path = seed()
    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
    print(f"Seeded {count} leases into {path}")
