# Case workflow

A refund case is an event log. The only legal path is intake, classified, proposed, approved, executed. `execute` from any earlier state raises. A proposed amount above the reason's cap raises and is not written, so the case stays classified. Replaying the log, including a duplicate event id, produces the same state.

Caps: duplicate charge 500, goodwill 25, shipping 40. The model may suggest a number. The cap is applied in code.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8008
```

Open http://127.0.0.1:8008. Describe a duplicate charge, then approve, then execute. Ask for a goodwill refund of 200 and the proposal is refused.

```powershell
..\.venv\Scripts\python -m pytest
```
