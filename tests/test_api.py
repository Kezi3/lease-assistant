import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import app  # noqa: E402
from leases import load_leases  # noqa: E402

client = TestClient(app)

# From the data file with today = 2026-11-04 and a 90 day window (ends 2027-02-02).
# L-004 expires on today's date, L-017 on the last day; L-011 expired yesterday, L-018 is the day after.
EXPECTED_90_DAY_IDS = ["L-001", "L-003", "L-004", "L-007", "L-017", "L-023", "L-035", "L-040"]


# ---- data sanity ----

def test_data_size_and_unique_ids():
    rows = load_leases()
    assert 30 <= len(rows) <= 50
    assert len({r["lease_id"] for r in rows}) == len(rows)


def test_status_is_derived_from_the_expiry_date_and_today():
    """Status is never stored, so it follows whatever 'today' is. Expiring today is still active."""
    for today in (date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2027, 6, 1)):
        for row in load_leases(today=today):
            expected = "expired" if date.fromisoformat(row["expires"]) < today else "active"
            assert row["status"] == expected, (today, row["lease_id"])


def test_data_has_a_useful_spread():
    expiries = [date.fromisoformat(r["expires"]) for r in load_leases()]
    today = date(2026, 11, 4)
    assert any(e < today for e in expiries)
    assert any(today <= e <= date(2027, 2, 2) for e in expiries)
    assert any(date(2027, 2, 3) <= e <= date(2027, 11, 4) for e in expiries)
    assert any(e > date(2027, 11, 4) for e in expiries)


# ---- endpoints ----

def test_list_all():
    res = client.get("/leases")
    assert res.status_code == 200
    assert len(res.json()) == len(load_leases())


def test_list_filters():
    expired = client.get("/leases", params={"status": "expired", "today": "2026-11-04"}).json()
    assert len(expired) == 5
    assert all(r["status"] == "expired" and r["expires"] < "2026-11-04" for r in expired)
    commercial = client.get("/leases", params={"property_type": "commercial"}).json()
    assert commercial and all(r["property_type"] == "commercial" for r in commercial)


def test_status_filter_follows_the_date_passed_in():
    """The stored column used to leave L-004 'active' after it expired. Now the date decides."""
    on_the_day = client.get("/leases", params={"status": "expired", "today": "2026-11-04"}).json()
    next_day = client.get("/leases", params={"status": "expired", "today": "2026-11-05"}).json()
    assert "L-004" not in {r["lease_id"] for r in on_the_day}  # expires 4 Nov: still active on 4 Nov
    assert "L-004" in {r["lease_id"] for r in next_day}        # expired by 5 Nov
    assert len(next_day) == len(on_the_day) + 1
    active_next_day = client.get("/leases", params={"status": "active", "today": "2026-11-05"}).json()
    assert len(active_next_day) + len(next_day) == len(load_leases())
    assert "L-004" not in {r["lease_id"] for r in active_next_day}


def test_list_rejects_unknown_filter_value():
    assert client.get("/leases", params={"status": "pending"}).status_code == 422


def test_get_one():
    res = client.get("/leases/L-001")
    assert res.status_code == 200
    body = res.json()
    assert body["property"] == "Unit A, Wuse 2"
    assert body["expires"] == "2026-12-15"


def test_get_one_status_follows_the_date_passed_in():
    assert client.get("/leases/L-004", params={"today": "2026-11-04"}).json()["status"] == "active"
    assert client.get("/leases/L-004", params={"today": "2026-11-05"}).json()["status"] == "expired"


def test_get_missing_returns_404():
    assert client.get("/leases/L-999").status_code == 404


def test_expiring_matches_ground_truth_and_is_sorted():
    res = client.get("/leases/expiring", params={"days": 90, "today": "2026-11-04"})
    assert res.status_code == 200
    rows = res.json()
    assert {r["lease_id"] for r in rows} == set(EXPECTED_90_DAY_IDS)
    dates = [r["expires"] for r in rows]
    assert dates == sorted(dates)


def test_expiring_window_edges():
    ids = {r["lease_id"] for r in client.get("/leases/expiring", params={"days": 90, "today": "2026-11-04"}).json()}
    assert "L-004" in ids      # expires today: included
    assert "L-017" in ids      # last day of the window: included
    assert "L-011" not in ids  # expired yesterday: excluded
    assert "L-018" not in ids  # first day after the window: excluded


def test_expiring_does_not_get_read_as_a_lease_id():
    assert client.get("/leases/expiring").status_code == 200


@pytest.mark.parametrize("days", [0, -5, 4000])
def test_expiring_rejects_bad_days(days):
    assert client.get("/leases/expiring", params={"days": days}).status_code == 422


def test_expiring_rejects_bad_date():
    assert client.get("/leases/expiring", params={"today": "not-a-date"}).status_code == 422
