import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import TOOLS, ToolError, ask_with_tools, run_tool, system_prompt  # noqa: E402

TODAY = date(2026, 11, 4)
# Leases expiring from 2026-11-04 up to and including 2027-02-02 (90 days).
EXPECTED_90_DAY_IDS = {"L-001", "L-003", "L-004", "L-007", "L-017", "L-023", "L-035", "L-040"}


def ids(result: dict) -> set[str]:
    return {lease["lease_id"] for lease in result["leases"]}


# ---- scripted stand-in for the Anthropic client (never touches the network) ----

def tool_use(tool_id: str, name: str, args: dict):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args)


def tool_reply(*blocks):
    return SimpleNamespace(stop_reason="tool_use", content=list(blocks))


def text_reply(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


class ScriptedClient:
    """Returns the scripted replies in order and records what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Copy the message list: the loop keeps appending to the same list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


FINAL = json.dumps({"answer": "ok", "lease_ids": ["L-001"]})


# ---- tool definitions ----

def test_tool_definitions_are_well_formed():
    names = [t["name"] for t in TOOLS]
    assert names == ["list_leases", "get_lease", "expiring_leases"]
    for tool in TOOLS:
        assert tool["description"].strip()
        assert tool["input_schema"]["type"] == "object"


def test_every_defined_tool_has_a_dispatcher_branch():
    valid_args = {"list_leases": {}, "get_lease": {"lease_id": "L-001"}, "expiring_leases": {"days": 1}}
    for tool in TOOLS:
        run_tool(tool["name"], valid_args[tool["name"]], TODAY)  # must not raise


# ---- the dispatcher ----

def test_list_leases_filters():
    expired = run_tool("list_leases", {"status": "expired"}, TODAY)
    assert expired["count"] == len(expired["leases"]) == 5
    assert all(lease["status"] == "expired" for lease in expired["leases"])
    commercial = run_tool("list_leases", {"property_type": "commercial"}, TODAY)
    assert commercial["count"] > 0 and all(l["property_type"] == "commercial" for l in commercial["leases"])
    assert run_tool("list_leases", {}, TODAY)["count"] == 40


def test_list_leases_rejects_bad_enum_value():
    with pytest.raises(ToolError, match="status must be one of"):
        run_tool("list_leases", {"status": "pending"}, TODAY)


def test_get_lease():
    assert run_tool("get_lease", {"lease_id": "L-001"}, TODAY)["property"] == "Unit A, Wuse 2"
    with pytest.raises(ToolError, match="No lease with id"):
        run_tool("get_lease", {"lease_id": "L-999"}, TODAY)
    with pytest.raises(ToolError, match="required"):
        run_tool("get_lease", {}, TODAY)


def test_expiring_by_days_matches_ground_truth_and_reports_the_window():
    result = run_tool("expiring_leases", {"days": 90}, TODAY)
    assert ids(result) == EXPECTED_90_DAY_IDS
    assert result["count"] == 8
    assert result["window"] == {"from": "2026-11-04", "to": "2027-02-02"}
    dates = [lease["expires"] for lease in result["leases"]]
    assert dates == sorted(dates)


def test_expiring_by_end_date_is_converted_to_days_in_code():
    by_date = run_tool("expiring_leases", {"end_date": "2027-02-02"}, TODAY)
    assert ids(by_date) == EXPECTED_90_DAY_IDS
    assert by_date["window"]["to"] == "2027-02-02"


def test_expiring_window_edges():
    result = run_tool("expiring_leases", {"days": 90}, TODAY)
    assert "L-004" in ids(result)      # expires today
    assert "L-017" in ids(result)      # last day of the window
    assert "L-011" not in ids(result)  # expired yesterday
    assert "L-018" not in ids(result)  # first day after the window


@pytest.mark.parametrize(
    "args, message",
    [
        ({}, "exactly one"),
        ({"days": 30, "end_date": "2027-01-01"}, "exactly one"),
        ({"end_date": "not-a-date"}, "YYYY-MM-DD"),
        ({"end_date": "2026-11-03"}, "before today"),
        ({"days": -1}, "0 to 3650"),
        ({"days": 4000}, "0 to 3650"),
        ({"days": True}, "0 to 3650"),
        ({"days": "90"}, "0 to 3650"),
        ({"days": 1.5}, "0 to 3650"),
    ],
)
def test_expiring_rejects_bad_arguments(args, message):
    with pytest.raises(ToolError, match=message):
        run_tool("expiring_leases", args, TODAY)


def test_unknown_tool():
    with pytest.raises(ToolError, match="Unknown tool"):
        run_tool("delete_lease", {"lease_id": "L-001"}, TODAY)


def test_missing_database_is_a_setup_error_not_a_tool_error(tmp_path, monkeypatch):
    """A broken setup must crash loudly, not be handed to the model as if it could fix it."""
    monkeypatch.setenv("LEASES_DB", str(tmp_path / "missing.db"))
    with pytest.raises(FileNotFoundError, match="seed_db.py"):
        run_tool("list_leases", {}, TODAY)


# ---- the loop ----

def test_loop_runs_the_requested_tool_and_returns_the_final_answer():
    final = json.dumps({"answer": "Eight leases expire by 2027-02-02.", "lease_ids": sorted(EXPECTED_90_DAY_IDS)})
    client = ScriptedClient(
        tool_reply(tool_use("toolu_1", "expiring_leases", {"days": 90})),
        text_reply(final),
    )
    result = ask_with_tools("Which leases expire in the next 90 days?", today=TODAY, client=client)

    assert result.steps == 2
    assert set(result.lease_ids) == EXPECTED_90_DAY_IDS
    assert [(c.name, c.input, c.is_error) for c in result.tool_calls] == [("expiring_leases", {"days": 90}, False)]

    # The second request must carry Claude's tool request and our result for it, matched by id.
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    tool_result = second[2]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert "is_error" not in tool_result
    assert set(json.loads(tool_result["content"])["leases"][i]["lease_id"] for i in range(8)) == EXPECTED_90_DAY_IDS


def test_loop_sends_tools_and_todays_date_to_the_model():
    client = ScriptedClient(text_reply(FINAL))
    ask_with_tools("hello", today=date(2026, 12, 1), client=client)
    request = client.requests[0]
    assert request["tools"] == TOOLS
    assert "2026-12-01" in request["system"]


def test_loop_uses_the_injected_date_for_the_window():
    client = ScriptedClient(
        tool_reply(tool_use("toolu_1", "expiring_leases", {"days": 30})),
        text_reply(FINAL),
    )
    result = ask_with_tools("q", today=date(2026, 12, 1), client=client)
    assert result.tool_calls[0].output["window"] == {"from": "2026-12-01", "to": "2026-12-31"}


def test_loop_feeds_tool_errors_back_so_the_model_can_recover():
    client = ScriptedClient(
        tool_reply(tool_use("toolu_1", "get_lease", {"lease_id": "L-999"})),
        tool_reply(tool_use("toolu_2", "get_lease", {"lease_id": "L-001"})),
        text_reply(FINAL),
    )
    result = ask_with_tools("q", today=TODAY, client=client)
    assert result.steps == 3
    assert [c.is_error for c in result.tool_calls] == [True, False]
    first_result = client.requests[1]["messages"][2]["content"][0]
    assert first_result["is_error"] is True and "No lease with id" in first_result["content"]


def test_loop_answers_every_tool_request_in_one_reply():
    client = ScriptedClient(
        tool_reply(
            tool_use("toolu_a", "get_lease", {"lease_id": "L-001"}),
            tool_use("toolu_b", "get_lease", {"lease_id": "L-002"}),
        ),
        text_reply(FINAL),
    )
    ask_with_tools("q", today=TODAY, client=client)
    results = client.requests[1]["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_a", "toolu_b"]


def test_loop_stops_after_the_step_limit():
    forever = [tool_reply(tool_use(f"toolu_{i}", "list_leases", {})) for i in range(10)]
    client = ScriptedClient(*forever)
    with pytest.raises(RuntimeError, match="No final answer after 3 model calls"):
        ask_with_tools("q", today=TODAY, client=client, max_steps=3)
    assert len(client.requests) == 3


def test_loop_rejects_a_final_reply_that_is_not_the_expected_json():
    client = ScriptedClient(text_reply("Eight leases expire soon."))
    with pytest.raises(ValueError, match="not valid answer JSON"):
        ask_with_tools("q", today=TODAY, client=client)


def test_loop_accepts_a_fenced_final_reply():
    client = ScriptedClient(text_reply(f"```json\n{FINAL}\n```"))
    assert ask_with_tools("q", today=TODAY, client=client).lease_ids == ["L-001"]


def test_loop_rejects_an_unexpected_stop_reason():
    client = ScriptedClient(text_reply("cut off", stop_reason="max_tokens"))
    with pytest.raises(RuntimeError, match="max_tokens"):
        ask_with_tools("q", today=TODAY, client=client)


def test_end_date_of_today_is_a_zero_day_window():
    result = run_tool("expiring_leases", {"end_date": "2026-11-04"}, TODAY)
    assert result["window"] == {"from": "2026-11-04", "to": "2026-11-04"}
    assert ids(result) == {"L-004"}  # the only lease expiring today


# ---- 'before' versus 'by', and status that follows today's date ----

def test_end_date_is_inclusive_so_by_and_before_differ_by_exactly_one_lease():
    """'By 31 Jan 2027' includes L-007 (expires 31 Jan). 'Before 31 Jan' means end_date 30 Jan, which does not."""
    by = run_tool("expiring_leases", {"end_date": "2027-01-31"}, TODAY)
    before = run_tool("expiring_leases", {"end_date": "2027-01-30"}, TODAY)
    assert ids(by) - ids(before) == {"L-007"}
    assert ids(before) <= ids(by)
    assert (before["window"]["to"], by["window"]["to"]) == ("2027-01-30", "2027-01-31")


def test_the_model_is_told_the_before_and_by_rule_in_both_places():
    expiring = next(t for t in TOOLS if t["name"] == "expiring_leases")
    assert "INCLUSIVE" in expiring["description"]
    assert "day BEFORE" in expiring["description"]
    assert "2027-01-30" in expiring["description"]  # the worked example
    assert "inclusive" in expiring["input_schema"]["properties"]["end_date"]["description"]
    rules = system_prompt(TODAY)
    assert "inclusive" in rules and "'before' a date means the day before it" in rules


def test_the_model_is_told_how_status_is_decided():
    listing = next(t for t in TOOLS if t["name"] == "list_leases")["description"]
    assert "before today" in listing and "expiring today is still 'active'" in listing


def test_list_leases_status_follows_today():
    on_the_day = run_tool("list_leases", {"status": "expired"}, date(2026, 11, 4))
    next_day = run_tool("list_leases", {"status": "expired"}, date(2026, 11, 5))
    assert "L-004" not in ids(on_the_day) and "L-004" in ids(next_day)
    assert next_day["count"] == on_the_day["count"] + 1
    active = run_tool("list_leases", {"status": "active", "property_type": "residential"}, date(2026, 11, 5))
    assert "L-004" not in ids(active)
    assert all(lease["status"] == "active" for lease in active["leases"])


def test_get_lease_status_follows_today():
    assert run_tool("get_lease", {"lease_id": "L-004"}, date(2026, 11, 4))["status"] == "active"
    assert run_tool("get_lease", {"lease_id": "L-004"}, date(2026, 11, 5))["status"] == "expired"


def test_loop_passes_its_date_to_the_status_filter():
    client = ScriptedClient(
        tool_reply(tool_use("toolu_1", "list_leases", {"status": "expired"})),
        text_reply(FINAL),
    )
    result = ask_with_tools("q", today=date(2026, 11, 5), client=client)
    assert result.tool_calls[0].output["count"] == 6  # the 5 expired by 4 Nov, plus L-004


# ---- the command line ----

def test_cli_prints_answer_ids_and_optional_trace(monkeypatch, capsys):
    import assistant

    fake = assistant.AssistantResult(
        answer="Two leases expire soon.",
        lease_ids=["L-001", "L-003"],
        tool_calls=[
            assistant.ToolCall("expiring_leases", {"days": 90}, {"count": 8, "leases": []}),
            assistant.ToolCall("get_lease", {"lease_id": "L-999"}, "No lease with id 'L-999'.", is_error=True),
        ],
        steps=3,
    )
    asked = []
    monkeypatch.setattr(assistant, "ask_with_tools", lambda question: asked.append(question) or fake)

    assistant.main(["assistant.py", "--trace", "Which", "leases", "expire?"])
    out = capsys.readouterr().out
    assert asked == ["Which leases expire?"]
    assert 'expiring_leases({"days": 90}) -> 8 lease(s)' in out
    assert "ERROR: No lease with id 'L-999'." in out
    assert "Two leases expire soon." in out
    assert "Leases: L-001, L-003" in out
    assert "(3 model calls, 2 tool calls)" in out

    assistant.main(["assistant.py"])
    plain = capsys.readouterr().out
    assert asked[-1] == "Which leases expire in the next 90 days?"
    assert "[tool 1]" not in plain
