"""Week 3: tool use. Claude chooses which lease query to run; our code runs it.

    python assistant.py "Which leases expire in the next 90 days?"
    python assistant.py --trace "How many commercial leases have expired?"

The flow, in plain words:
  1. We send the question plus a list of tools (name, description, input schema).
  2. Claude replies either with a final answer or with a request to call a tool.
  3. If it asks for a tool, WE run it (run_tool below) and send the result back.
  4. Repeat until Claude gives its final answer, or we hit the step limit.

Claude never touches the database and never does date arithmetic: the date
window is computed in code (leases.query_expiring_leases).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from leases import get_lease_by_id, load_leases, query_expiring_leases
from main import MODEL

load_dotenv()

MAX_STEPS = 6  # model calls per question; stops a confused loop from running forever
STATUSES = ["active", "expired"]
PROPERTY_TYPES = ["residential", "commercial"]

# ---------------------------------------------------------------------------
# 1. Tool definitions: what Claude is told it can ask for.
#    The descriptions matter most. Claude picks a tool by reading them.
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "list_leases",
        "description": (
            "List leases, optionally filtered by status and/or property type. "
            "Use this for questions about all leases, counts, rents, or expired leases. "
            "Do not use it for 'expiring soon' questions: use expiring_leases for those. "
            "Returns the count and every matching lease."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": STATUSES, "description": "Only leases with this status."},
                "property_type": {"type": "string", "enum": PROPERTY_TYPES, "description": "Only this type."},
            },
        },
    },
    {
        "name": "get_lease",
        "description": (
            "Get one lease by its id, for example 'L-001'. "
            "Use this when the question names a specific lease id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"lease_id": {"type": "string", "description": "Lease id such as 'L-001'."}},
            "required": ["lease_id"],
        },
    },
    {
        "name": "expiring_leases",
        "description": (
            "Leases whose expiry date falls from today up to and including the end of a window. "
            "Give exactly one of: 'days' (for 'in the next N days') or 'end_date' "
            "(for 'before/by a date'). The window is calculated in code, so never work it out yourself. "
            "Returns the window dates, the count, and the leases soonest first. "
            "Leases that have already expired are not included."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 0, "maximum": 3650, "description": "Window length in days from today."},
                "end_date": {"type": "string", "description": "Last day of the window, as YYYY-MM-DD."},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# 2. The dispatcher: what actually runs when Claude asks for a tool.
#    Claude's inputs are untrusted, so every argument is checked here.
#    A ToolError is sent back to Claude as an error result so it can correct itself.
# ---------------------------------------------------------------------------
class ToolError(Exception):
    """A tool call that was wrong in a way Claude can fix (bad argument, unknown id)."""


def _enum_arg(args: dict, key: str, allowed: list[str]) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if value not in allowed:
        raise ToolError(f"{key} must be one of {allowed}, got {value!r}.")
    return value


def run_tool(name: str, args: dict, today: date) -> dict:
    if name == "list_leases":
        rows = load_leases(
            status=_enum_arg(args, "status", STATUSES),
            property_type=_enum_arg(args, "property_type", PROPERTY_TYPES),
        )
        return {"count": len(rows), "leases": rows}

    if name == "get_lease":
        lease_id = args.get("lease_id")
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise ToolError("lease_id is required, for example 'L-001'.")
        row = get_lease_by_id(lease_id.strip())
        if row is None:
            raise ToolError(f"No lease with id {lease_id!r}. Lease ids look like 'L-001'.")
        return row

    if name == "expiring_leases":
        days, end_date = args.get("days"), args.get("end_date")
        if (days is None) == (end_date is None):
            raise ToolError("Provide exactly one of 'days' or 'end_date'.")
        if end_date is not None:
            try:
                days = (date.fromisoformat(end_date) - today).days
            except (TypeError, ValueError):
                raise ToolError(f"end_date must be a YYYY-MM-DD date, got {end_date!r}.") from None
            if days < 0:
                raise ToolError(f"end_date {end_date} is before today ({today.isoformat()}).")
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 3650:
            raise ToolError(f"days must be a whole number from 0 to 3650, got {days!r}.")
        rows = query_expiring_leases(today, days)
        window = {"from": today.isoformat(), "to": (today + timedelta(days=days)).isoformat()}
        return {"window": window, "count": len(rows), "leases": rows}

    raise ToolError(f"Unknown tool {name!r}.")


# ---------------------------------------------------------------------------
# 3. The loop.
# ---------------------------------------------------------------------------
class ToolAnswer(BaseModel):
    answer: str
    lease_ids: list[str]


@dataclass
class ToolCall:
    name: str
    input: dict
    output: dict | str  # the result dict, or the error message
    is_error: bool = False


@dataclass
class AssistantResult:
    answer: str
    lease_ids: list[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    steps: int = 0  # number of model calls used


def system_prompt(today: date) -> str:
    return (
        "You answer questions about a portfolio of leases using the tools provided.\n"
        f"Today's date is {today.isoformat()}.\n"
        "Rules:\n"
        "- Get every lease fact from the tools. Never guess and never rely on memory.\n"
        "- Never work out a date window yourself. For 'in the next N days' call expiring_leases "
        "with days; for 'before' or 'by' a date call it with end_date.\n"
        "- If the tools cannot answer the question, say so in the answer and return no lease ids.\n"
        "- When you are finished, reply with JSON only and no other text, shaped like "
        '{"answer": str, "lease_ids": [str]}. "answer" is a short plain-English answer that states '
        'the dates it used. "lease_ids" lists the ids of the leases the answer is about.'
    )


def parse_final(text: str) -> ToolAnswer:
    """Parse Claude's final reply. Tolerates code fences; fails loudly otherwise."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return ToolAnswer.model_validate_json(cleaned)
    except ValueError as err:
        raise ValueError(f"Final reply was not valid answer JSON: {err}\nReply was: {text!r}") from err


def ask_with_tools(
    question: str,
    today: date | None = None,
    client: Anthropic | None = None,
    max_steps: int = MAX_STEPS,
) -> AssistantResult:
    today = today or date.today()
    client = client or Anthropic()
    system = system_prompt(today)
    messages: list[dict] = [{"role": "user", "content": question}]
    calls: list[ToolCall] = []

    for step in range(1, max_steps + 1):
        reply = client.messages.create(
            model=MODEL, max_tokens=2000, system=system, tools=TOOLS, messages=messages
        )

        if reply.stop_reason == "tool_use":
            # Keep Claude's request in the conversation, then answer every tool_use block in it.
            messages.append({"role": "assistant", "content": reply.content})
            results = []
            for block in reply.content:
                if block.type != "tool_use":
                    continue
                try:
                    output = run_tool(block.name, block.input, today)
                    result = {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output)}
                    calls.append(ToolCall(block.name, dict(block.input), output))
                except ToolError as err:
                    result = {"type": "tool_result", "tool_use_id": block.id, "content": str(err), "is_error": True}
                    calls.append(ToolCall(block.name, dict(block.input), str(err), is_error=True))
                results.append(result)
            messages.append({"role": "user", "content": results})
            continue

        if reply.stop_reason == "end_turn":
            text = next((b.text for b in reply.content if b.type == "text"), None)
            if text is None:
                raise RuntimeError("The model finished without a text answer.")
            final = parse_final(text)
            return AssistantResult(final.answer, final.lease_ids, calls, step)

        raise RuntimeError(f"Unexpected stop_reason {reply.stop_reason!r}.")

    raise RuntimeError(
        f"No final answer after {max_steps} model calls. Tools called: {[c.name for c in calls]}"
    )


# ---------------------------------------------------------------------------
# 4. Command line
# ---------------------------------------------------------------------------
def _summarise(call: ToolCall) -> str:
    if call.is_error:
        return f"ERROR: {call.output}"
    out = call.output
    return f"{out['count']} lease(s)" if isinstance(out, dict) and "count" in out else "ok"


def main(argv: list[str]) -> None:
    args = argv[1:]
    trace = bool(args) and args[0] == "--trace"
    if trace:
        args = args[1:]
    question = " ".join(args) or "Which leases expire in the next 90 days?"

    result = ask_with_tools(question)
    if trace:
        for i, call in enumerate(result.tool_calls, start=1):
            print(f"[tool {i}] {call.name}({json.dumps(call.input)}) -> {_summarise(call)}")
        print()
    print(result.answer)
    print("Leases:", ", ".join(result.lease_ids) or "none")
    print(f"({result.steps} model calls, {len(result.tool_calls)} tool calls)")


if __name__ == "__main__":
    main(sys.argv)
