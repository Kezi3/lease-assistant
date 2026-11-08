"""Small read-only API over the invented lease records.

Run:  uvicorn api:app --reload      then open http://127.0.0.1:8000/docs
"""
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from leases import get_lease_by_id, load_leases, query_expiring_leases

app = FastAPI(title="Lease Assistant API", version="0.2.0")


@app.exception_handler(FileNotFoundError)
def database_missing(request: Request, exc: FileNotFoundError):
    """A missing database is a setup problem, not a crash: say how to fix it."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


class LeaseRecord(BaseModel):
    lease_id: str
    property: str
    tenant: str
    expires: date
    rent_ngn: int
    property_type: Literal["residential", "commercial"]
    status: Literal["active", "expired"]


TODAY_PARAM = Query(None, description="Override today's date (YYYY-MM-DD), for testing")


@app.get("/leases", response_model=list[LeaseRecord])
def list_leases(
    status: Literal["active", "expired"] | None = None,
    property_type: Literal["residential", "commercial"] | None = None,
    today: date | None = TODAY_PARAM,
):
    """All leases, optionally filtered by status and/or property type.

    `status` is worked out from the expiry date and today, not stored: a lease is
    `expired` once its expiry date is before today.
    """
    rows = load_leases(status=status, property_type=property_type, today=today)
    return [LeaseRecord(**row) for row in rows]


# Declared before /leases/{lease_id} so "expiring" is not read as a lease id.
@app.get("/leases/expiring", response_model=list[LeaseRecord])
def expiring_leases(
    days: int = Query(90, ge=1, le=3650, description="Window length in days, counted from today"),
    today: date | None = TODAY_PARAM,
):
    """Leases expiring from today up to and including `days` days from today, soonest first."""
    rows = query_expiring_leases(today or date.today(), days)
    return sorted((LeaseRecord(**row) for row in rows), key=lambda r: r.expires)


@app.get("/leases/{lease_id}", response_model=LeaseRecord)
def get_lease(lease_id: str, today: date | None = TODAY_PARAM):
    row = get_lease_by_id(lease_id, today=today)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Lease {lease_id} not found")
    return LeaseRecord(**row)
