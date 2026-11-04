import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import Answer, ask, leases_expiring_within, load_leases, parse_answer  # noqa: E402

TODAY = date(2026, 11, 4)


def properties(items) -> set[str]:
    return {item["property"] if isinstance(item, dict) else item.property for item in items}


def test_90_day_ground_truth():
    """4 Nov 2026 + 90 days = 2 Feb 2027: Unit A (15 Dec) and Unit C (10 Jan) fall inside, Unit B does not."""
    result = leases_expiring_within(load_leases(), TODAY, 90)
    assert properties(result) == {"Unit A, Wuse 2", "Unit C, Maitama"}


def test_window_boundaries():
    leases = [
        {"property": "Today", "tenant": "T", "expires": "2026-11-04"},
        {"property": "Last day", "tenant": "T", "expires": "2027-02-02"},
        {"property": "Day after", "tenant": "T", "expires": "2027-02-03"},
        {"property": "Already expired", "tenant": "T", "expires": "2026-11-03"},
    ]
    assert properties(leases_expiring_within(leases, TODAY, 90)) == {"Today", "Last day"}


def test_parse_plain_json():
    out = parse_answer('{"answer": "Two leases.", "leases": []}')
    assert isinstance(out, Answer) and out.leases == []


def test_parse_fenced_json():
    out = parse_answer('```json\n{"answer": "ok", "leases": []}\n```')
    assert out.answer == "ok"


def test_parse_rejects_bad_reply():
    with pytest.raises(ValueError):
        parse_answer("Sure! Here are the leases that expire soon.")


def test_parse_rejects_wrong_shape():
    with pytest.raises(ValueError):
        parse_answer('{"answer": "ok"}')


class FakeClient:
    """Stands in for Anthropic so tests never call the network."""

    def __init__(self, text: str):
        self.text = text
        self.last_prompt = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.last_prompt = kwargs["messages"][0]["content"]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_ask_uses_injected_date_and_returns_validated_answer():
    reply = (
        '{"answer": "Two leases expire.", "leases": ['
        '{"property": "Unit A, Wuse 2", "tenant": "Tenant 1", "expires": "2026-12-15"},'
        '{"property": "Unit C, Maitama", "tenant": "Tenant 3", "expires": "2027-01-10"}]}'
    )
    client = FakeClient(reply)
    out = ask("Which leases expire in the next 90 days?", today=TODAY, client=client)
    assert "2026-11-04" in client.last_prompt
    expected = properties(leases_expiring_within(load_leases(), TODAY, 90))
    assert properties(out.leases) == expected
