# Lease Assistant

An AI query assistant over lease records. Ask a question in plain English, for example "Which leases expire in the next 90 days?", and get a structured JSON answer from the Claude API.

**Status:** Week 2 of a 6 week build. There is a CLI that sends a question and the records to Claude and validates the JSON that comes back, and a small read-only API over the records. The API and CLI read from SQLite; `data/leases.json` is the public seed. Next: tool use so Claude chooses which query to run (Week 3), and a scored test set (Week 4).

## Data

All 40 records in `data/leases.json` are invented. No real tenants, properties or rents are used. Each record has `lease_id`, `property`, `tenant`, `expires`, `rent_ngn`, `property_type` and `status`.

The expiry dates are deliberately spread: some already expired, some inside the next 90 days (including a lease expiring today and one on the last day of the window), some a few months out, and some years out. Statuses are a snapshot as of 4 Nov 2026.

`data/leases.json` stays in the repo as the seed source. Build (or rebuild) the SQLite database with:

```bash
python seed_db.py
```

That writes `data/leases.db` (gitignored). Running the script twice drops and recreates the table so the database matches the JSON. The API and `load_leases()` read this database, not the JSON file directly. Tests seed a temporary `.db` and never use a committed database.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pytest
python seed_db.py                # builds data/leases.db from data/leases.json
cp .env.example .env             # then put your Anthropic API key in .env
```

## Ask a question (CLI)

```bash
python main.py
```

## Run the API

```bash
uvicorn api:app --reload
```

Open http://127.0.0.1:8000/docs to try the endpoints.

| Endpoint | What it returns |
|---|---|
| `GET /leases` | All leases. Optional filters: `status` (`active`, `expired`) and `property_type` (`residential`, `commercial`). |
| `GET /leases/{lease_id}` | One lease, or 404. |
| `GET /leases/expiring?days=90` | Leases expiring from today up to and including `days` days out, soonest first. `days` must be 1 to 3650. An optional `today=YYYY-MM-DD` overrides the date, for testing. |

## Test it

```bash
pytest
```

The tests never call the Claude API. They check the seeded SQLite data, the API endpoints, the date-window logic (including both edges), the JSON validation, and that `ask()` uses the date it is given. Each run builds a temporary database from `data/leases.json`.

## Accuracy

Not yet measured. A results table will be added in Week 4.
