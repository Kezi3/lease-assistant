import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_db  # noqa: E402
from api import app  # noqa: E402
from leases import (  # noqa: E402
    get_lease_by_id,
    leases_expiring_within,
    load_leases,
    query_expiring_leases,
)

TODAY = date(2026, 11, 4)


def test_database_holds_all_seed_rows():
    assert len(load_leases()) == 40


def test_sql_filters_match_python_filters():
    rows = load_leases()
    assert load_leases(status="expired") == [r for r in rows if r["status"] == "expired"]
    assert load_leases(property_type="commercial") == [r for r in rows if r["property_type"] == "commercial"]
    both = load_leases(status="active", property_type="residential")
    assert both == [r for r in rows if r["status"] == "active" and r["property_type"] == "residential"]


@pytest.mark.parametrize("days", [1, 30, 90, 180, 365, 3650])
@pytest.mark.parametrize("offset", [-30, 0, 1, 45, 120, 400])
def test_sql_expiring_matches_python_ground_truth(days, offset):
    today = TODAY + timedelta(days=offset)
    from_sql = {r["lease_id"] for r in query_expiring_leases(today, days)}
    from_python = {r["lease_id"] for r in leases_expiring_within(load_leases(), today, days)}
    assert from_sql == from_python


def test_expiring_results_are_ordered_by_date():
    dates = [r["expires"] for r in query_expiring_leases(TODAY, 365)]
    assert dates == sorted(dates)


def test_lookup_is_parameterised():
    assert get_lease_by_id("L-001' OR '1'='1") is None
    assert get_lease_by_id("L-001")["property"] == "Unit A, Wuse 2"


def test_seeding_twice_does_not_duplicate_rows(tmp_path):
    db = tmp_path / "twice.db"
    seed_db.seed(db)
    seed_db.seed(db)
    assert len(load_leases(db)) == 40


def test_seed_script_honours_leases_db_env_var(tmp_path, monkeypatch):
    """seed_db.py and leases.py must agree on where the database lives."""
    target = tmp_path / "from_env.db"
    monkeypatch.setenv("LEASES_DB", str(target))
    assert seed_db.seed() == target
    assert len(load_leases()) == 40


def test_missing_database_raises_clear_error_and_creates_nothing(tmp_path):
    db = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError, match="seed_db.py"):
        load_leases(db)
    assert not db.exists()


def test_api_reports_missing_database_as_503(tmp_path, monkeypatch):
    monkeypatch.setenv("LEASES_DB", str(tmp_path / "missing.db"))
    res = TestClient(app).get("/leases")
    assert res.status_code == 503
    assert "seed_db.py" in res.json()["detail"]
    assert not (tmp_path / "missing.db").exists()
