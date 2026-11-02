import json
from datetime import date
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()

LEASES = [
    {"property": "Unit A, Wuse 2", "tenant": "Tenant 1", "expires": "2026-12-15"},
    {"property": "Unit B, Garki", "tenant": "Tenant 2", "expires": "2027-06-30"},
    {"property": "Unit C, Maitama", "tenant": "Tenant 3", "expires": "2027-01-10"},
]

def ask(question: str) -> dict:
    prompt = (
        f"Today is {date.today().isoformat()}. Here are the leases: {json.dumps(LEASES)}\n"
        f"Question: {question}\n"
        'Reply with JSON only, shaped like {"answer": str, "leases": [ ... ]}.'
    )
    reply = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in reply.content if b.type == "text")
    return json.loads(text)

if __name__ == "__main__":
    print(json.dumps(ask("Which leases expire in the next 90 days?"), indent=2))