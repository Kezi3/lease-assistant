"""Run the loop through the REAL Anthropic SDK, with the HTTP layer replaced by a canned server.

The scripted-client tests prove our logic. This one proves the SDK accepts our request shape
and can send Claude's own tool_use block back to it. It needs no API key and no network.
"""
import json
import sys
from datetime import date
from pathlib import Path

import httpx2
from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import TOOLS, ask_with_tools  # noqa: E402

TODAY = date(2026, 11, 4)


def message_json(content: list[dict], stop_reason: str) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def make_client(replies: list[dict]) -> tuple[Anthropic, list[dict]]:
    sent: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=replies.pop(0))

    client = Anthropic(
        api_key="test-key",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    return client, sent


def test_full_round_trip_through_the_real_sdk():
    final = {"answer": "Eight leases expire by 2027-02-02.", "lease_ids": ["L-001", "L-003"]}
    client, sent = make_client(
        [
            message_json(
                [{"type": "tool_use", "id": "toolu_01", "name": "expiring_leases", "input": {"days": 90}}],
                "tool_use",
            ),
            message_json([{"type": "text", "text": json.dumps(final)}], "end_turn"),
        ]
    )

    result = ask_with_tools("Which leases expire in the next 90 days?", today=TODAY, client=client)

    assert result.lease_ids == ["L-001", "L-003"]
    assert result.steps == 2 and len(sent) == 2

    first, second = sent
    assert first["model"] == "claude-sonnet-5-5"
    assert [t["name"] for t in first["tools"]] == [t["name"] for t in TOOLS]
    assert "2026-11-04" in first["system"]
    assert first["messages"] == [{"role": "user", "content": "Which leases expire in the next 90 days?"}]

    # Claude's tool_use block went back to the API intact, followed by our result for it.
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["user", "assistant", "user"]
    echoed = second["messages"][1]["content"][0]
    assert (echoed["type"], echoed["id"], echoed["name"], echoed["input"]) == (
        "tool_use", "toolu_01", "expiring_leases", {"days": 90},
    )
    tool_result = second["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_01"
    assert json.loads(tool_result["content"])["window"] == {"from": "2026-11-04", "to": "2027-02-02"}
