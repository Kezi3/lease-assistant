"""Point the suite at a temporary SQLite DB seeded from data/leases.json."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from seed_db import seed  # noqa: E402


def pytest_configure(config):
    tmp_dir = Path(tempfile.mkdtemp(prefix="lease-assistant-"))
    db_path = tmp_dir / "leases.db"
    seed(db_path)
    os.environ["LEASES_DB"] = str(db_path)
