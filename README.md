# Lease Assistant

An AI query assistant over lease records. Ask a question in plain English, for example "Which leases expire in the next 90 days?", and get a structured JSON answer from the Claude API.

**Status:** Week 3 of a 6 week build. There is a small read-only API over the records in SQLite, and an assistant (`assistant.py`) where Claude chooses which query to run using tool use. The older `main.py` CLI, which pastes every record into the prompt, is kept for comparison. Next: a scored test set (Week 4).

## Data

All 40 records in `data/leases.json` are invented. No real tenants, properties or rents are used. Each record has `lease_id`, `property`, `tenant`, `expires`, `rent_ngn`, `property_type` and `status`.

The expiry dates are deliberately spread: some already expired, some inside the next 90 days (including a lease expiring today and one on the last day of the window), some a few months out, and some years out. Statuses are a snapshot as of 4 Nov 2026.

`data/leases.json` stays in the repo as the seed source. Build (or rebuild) the SQLite database with:

```bash
python seed_db.py
```

That writes `data/leases.db` (gitignored). Running the script twice drops and recreates the table so the database matches the JSON. The API and `load_leases()` read this database, not the JSON file directly. Tests seed a temporary `.db` and never use a committed database.

To keep the database somewhere else, set `LEASES_DB` to a file path; both `seed_db.py` and the API honour it. If the database has not been built, the API answers `503` with the message "Build it with: python seed_db.py" instead of crashing.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pytest
python seed_db.py                # builds data/leases.db from data/leases.json
cp .env.example .env             # then put your Anthropic API key in .env
```

## Ask a question (tool use)

```bash
python assistant.py "Which leases expire in the next 90 days?"
python assistant.py --trace "How many commercial leases have expired?"
```

`--trace` prints which tool Claude chose and what it got back, one line per call. This is the quickest way to see tool use working. Needs `ANTHROPIC_API_KEY` in `.env`; without it the SDK stops with "Could not resolve authentication method".

How it works:

1. We send the question and three tool definitions: `list_leases`, `get_lease` and `expiring_leases`.
2. Claude replies with a final answer, or asks for a tool by name with arguments.
3. If it asks for a tool, our code runs it (`run_tool`) and sends the result back.
4. This repeats until Claude gives its final answer as JSON, or the step limit (6 model calls) is reached.

Design decisions to know about:

- **Date windows are calculated in code.** Claude passes `days` or an `end_date`; `leases.query_expiring_leases` does the arithmetic. Claude is told never to work out a window itself, which fixes the earlier problem of the model's own date arithmetic varying between runs.
- **Claude's arguments are untrusted.** `run_tool` validates every argument. A bad argument or unknown lease id goes back to Claude as an error result so it can correct itself. A broken setup (for example a missing database) crashes loudly instead, because Claude cannot fix that.
- **Tools only read.** There is no tool that changes data.

## Ask a question (older CLI)

```bash
python main.py
```

Sends all records in the prompt and lets the model do the date arithmetic itself. Kept so the two approaches can be compared in Week 4.

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

For tool use, `tests/test_assistant.py` runs the loop against a scripted stand-in for Claude, and `tests/test_assistant_sdk.py` runs it through the real Anthropic SDK with the HTTP layer replaced by a canned server. That proves the request and tool-result shapes are accepted by the SDK, but only a live run shows how Claude itself chooses tools.

## Accuracy

Not yet measured. A results table will be added in Week 4.
