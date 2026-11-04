"""Small read-only API over the invented lease records.

Run:  uvicorn api:app --reload      then open http://127.0.0.1:8000/docs
"""
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from leases import leases_expiring_within, load_leases

app = FastAPI(title="Lease Assistant API", version="0.2.0")


class LeaseRecord(BaseModel):
    lease_id: str
    property: str
    tenant: str
    expires: date
    rent_ngn: int
    property_type: Literal["residential", "commercial"]
    status: Literal["active", "expired"]


def _records() -> list[LeaseRecord]:
    return [LeaseRecord(**row) for row in load_leases()]


@app.get("/leases", response_model=list[LeaseRecord])
def list_leases(
    status: Literal["active", "expired"] | None = None,
    property_type: Literal["residential", "commercial"] | None = None,
):
    """All leases, optionally filtered by status and/or property type."""
    records = _records()
    if status:
        records = [r for r in records if r.status == status]
    if property_type:
        records = [r for r in records if r.property_type == property_type]
    return records


# Declared before /leases/{lease_id} so "expiring" is not read as a lease id.
@app.get("/leases/expiring", response_model=list[LeaseRecord])
def expiring_leases(
    days: int = Query(90, ge=1, le=3650, description="Window length in days, counted from today"),
    today: date | None = Query(None, description="Override today's date (YYYY-MM-DD), for testing"),
):
    """Leases expiring from today up to and including `days` days from today, soonest first."""
    rows = leases_expiring_within(load_leases(), today or date.today(), days)
    return sorted((LeaseRecord(**row) for row in rows), key=lambda r: r.expires)


@app.get("/leases/{lease_id}", response_model=LeaseRecord)
def get_lease(lease_id: str):
    for record in _records():
        if record.lease_id == lease_id:
            return record
    raise HTTPException(status_code=404, detail=f"Lease {lease_id} not found")
