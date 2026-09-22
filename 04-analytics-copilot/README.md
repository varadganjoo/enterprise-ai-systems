# Analytics copilot

Questions that match the catalog compile to a named metric. If the model also emits SQL, including a delete, that SQL is ignored and the metric runs.

English questions become one SQLite SELECT. The SELECT is checked, then run on a read-only connection. The answer text is rendered from the cells that came back. `DELETE`, a second statement, and a comment hiding a write never run.

Completed-order revenue for March 2026 is 400. Three tickets are open. Cho East has the highest completed revenue, 500, because Ben's February order is cancelled.

The model is `gemini-3.8-flash`. No other API key is required.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8004
```

Open http://127.0.0.1:8004. Ask for March revenue, then try "Delete all tickets."

```powershell
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\python evals\run_eval.py
```

The golden file holds reference SQL. The score is whether the model's executed cells match that reference, not whether the SQL string matches. The delete question passes when nothing is executed and the ticket count is unchanged.
