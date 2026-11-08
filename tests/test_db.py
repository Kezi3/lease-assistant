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
    """Expectations come from the raw expiry dates, not from the derived status being tested."""
    rows = load_leases(today=TODAY)
    iso = TODAY.isoformat()
    assert load_leases(status="expired", today=TODAY) == [r for r in rows if r["expires"] < iso]
    assert load_leases(status="active", today=TODAY) == [r for r in rows if r["expires"] >= iso]
    assert load_leases(property_type="commercial", today=TODAY) == [
        r for r in rows if r["property_type"] == "commercial"
    ]
    both = load_leases(status="active", property_type="residential", today=TODAY)
    assert both == [r for r in rows if r["expires"] >= iso and r["property_type"] == "residential"]


def test_expired_and_active_partition_the_leases():
    for offset in (-100, 0, 1, 30, 200, 1000):
        today = TODAY + timedelta(days=offset)
        expired = {r["lease_id"] for r in load_leases(status="expired", today=today)}
        active = {r["lease_id"] for r in load_leases(status="active", today=today)}
        assert not expired & active
        assert len(expired) + len(active) == 40


def test_a_lease_expiring_today_is_active_and_yesterdays_is_expired():
    assert get_lease_by_id("L-004", today=date(2026, 11, 4))["status"] == "active"
    assert get_lease_by_id("L-004", today=date(2026, 11, 5))["status"] == "expired"
    assert get_lease_by_id("L-011", today=date(2026, 11, 4))["status"] == "expired"  # expired 3 Nov


def test_every_read_path_returns_a_derived_status():
    today = date(2026, 11, 5)
    assert {r["status"] for r in load_leases(today=today)} == {"active", "expired"}
    assert get_lease_by_id("L-004", today=today)["status"] == "expired"
    assert {r["status"] for r in query_expiring_leases(today, 90)} == {"active"}


def test_status_is_not_stored_in_the_database():
    import sqlite3
    from contextlib import closing

    from leases import resolve_db_path

    with closing(sqlite3.connect(resolve_db_path())) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(leases)")]
    assert "status" not in columns


def test_a_database_built_before_this_change_still_works(tmp_path):
    """Existing databases still have the old stale status column. It must be ignored, not trusted."""
    import sqlite3
    from contextlib import closing

    old = tmp_path / "old.db"
    with closing(sqlite3.connect(old)) as conn, conn:
        conn.execute(
            "CREATE TABLE leases (lease_id TEXT PRIMARY KEY, property TEXT, tenant TEXT, expires TEXT, "
            "rent_ngn INTEGER, property_type TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO leases VALUES ('L-004', 'Unit 4, Gwarinpa', 'Tenant 4', '2026-11-04', 3500000, "
            "'residential', 'active')"  # stored 'active', but long past expiry by the date used below
        )
    row = load_leases(old, today=date(2026, 11, 8))[0]
    assert row["status"] == "expired"
    assert [r["lease_id"] for r in load_leases(old, status="expired", today=date(2026, 11, 8))] == ["L-004"]


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError, match="status must be"):
        load_leases(status="pending", today=TODAY)


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
