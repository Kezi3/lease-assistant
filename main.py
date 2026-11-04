import json
import re
from datetime import date

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from leases import DATA_FILE, leases_expiring_within, load_leases  # noqa: F401

load_dotenv()

MODEL = "claude-sonnet-5-5"


class Lease(BaseModel):
    property: str
    tenant: str
    expires: str


class Answer(BaseModel):
    answer: str
    leases: list[Lease]


def parse_answer(text: str) -> Answer:
    """Parse the model's reply into an Answer. Tolerates code fences; fails loudly otherwise."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return Answer.model_validate_json(cleaned)
    except ValueError as err:
        raise ValueError(f"Model reply was not valid Answer JSON: {err}\nReply was: {text!r}") from err


def ask(question: str, today: date | None = None, client: Anthropic | None = None) -> Answer:
    today = today or date.today()
    client = client or Anthropic()
    prompt = (
        f"Today is {today.isoformat()}. Here are the leases: {json.dumps(load_leases())}\n"
        f"Question: {question}\n"
        'Reply with JSON only, shaped like {"answer": str, "leases": [{"property": str, "tenant": str, "expires": str}]}.'
    )
    reply = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in reply.content if b.type == "text")
    return parse_answer(text)


if __name__ == "__main__":
    print(ask("Which leases expire in the next 90 days?").model_dump_json(indent=2))
