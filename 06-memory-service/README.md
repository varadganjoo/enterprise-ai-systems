# Memory service

A slot such as `seat_preference` holds one active value. Writing a new value for that slot supersedes the old row instead of keeping both.

Each session has a memory table. Add, correct, and forget are applied in code. A correction marks the old row superseded and inserts a new active row. Recall, including the reply when you ask what is remembered, reads only active rows. If two memories are active and a correction does not name an id, nothing is changed.

Messages that match a local list (social security number, password, credit card, CVV) are refused before any Gemini call, and the secret is not written. The model is `gemini-3.8-flash` for ordinary turns. No other API key is required.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8006
```

Open http://127.0.0.1:8006. Say you prefer aisle seats, then that you actually prefer window seats, then ask what you prefer. The history column should keep the aisle row struck through.

```powershell
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\python evals\run_eval.py
```

The unit tests cover correction, forget, the sensitive block, duplicate adds, and the refusal to guess which memory to replace. The eval script is a live conversation and checks the table, not only the prose.
