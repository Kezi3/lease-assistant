# Lease Assistant

An AI query assistant over lease records. Ask a question in plain English, for example "Which leases expire in the next 90 days?", and get a structured JSON answer from the Claude API.

**Status:** Week 1 of a 6 week build. Today it sends the question and the records to Claude and validates the JSON that comes back. Next: a FastAPI service (Week 2), tool use so Claude chooses which query to run (Week 3), and a scored test set (Week 4).

## Data

All records in `data/leases.json` are invented. No real tenants, properties or rents are used.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your Anthropic API key in .env
python main.py
```

## Test it

```bash
pip install pytest
pytest
```

The tests never call the API. They check the date-window ground truth, the JSON validation, and that `ask()` uses the date it is given.

## Accuracy

Not yet measured. A results table will be added in Week 4.
