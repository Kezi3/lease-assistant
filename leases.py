"""Lease data access and date logic, shared by the CLI (main.py) and the API (api.py)."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "leases.json"


def load_leases(path: Path = DATA_FILE) -> list[dict]:
    return json.loads(path.read_text())


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
