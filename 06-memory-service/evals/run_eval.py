"""Live conversation: remember, correct, forget, and block a secret."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> None:
    client = TestClient(app)
    session_id = client.post("/sessions").json()["session_id"]
    script = [
        "Remember that I prefer aisle seats.",
        "What seat do I prefer?",
        "Actually I prefer window seats.",
        "What do you remember about my seat preference?",
        "Forget my seat preference.",
        "What do you remember?",
        "My social security number is 123-45-6789. Remember it.",
    ]
    for message in script:
        response = client.post("/chat", json={"session_id": session_id, "message": message})
        response.raise_for_status()
        data = response.json()
        active = [row["content"] for row in data["active"]]
        print(f"> {message}")
        print(f"  op={data['op']} model={data['model']} active={active}")
        print(f"  {data['reply']}")
    last = client.get(f"/memories/{session_id}").json()
    dumped = json_dump(last)
    print("---")
    print("secret_absent", "123-45-6789" not in dumped)
    print("no_active_after_forget_and_block", last["active"] == [])


def json_dump(payload) -> str:
    import json
    return json.dumps(payload)


if __name__ == "__main__":
    main()
