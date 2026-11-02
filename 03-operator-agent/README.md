# Operator agent

Outbound text that says a refund or payment already happened is rejected before it is stored. Queueing the same body twice returns the existing approval.

A support agent with six tools. `propose_send` inserts a pending approval and leaves the ticket open. The approve endpoint records the stored body as sent in the local database; no email provider is connected. A second decision is rejected. The loop stops at 6 steps or 12,000 tokens.

The default model is `gemini-3.8-flash`, configurable through `GEMINI_MODEL`. No other API key is required.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8003
```

Open http://127.0.0.1:8003. Ask it to reply to Ada North. The trace should queue an approval, and the ticket should stay open until you press Approve stored text.

```powershell
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\python evals\run_eval.py
```

The unit tests never call Gemini. They prove a queued send is not a sent email, and that approving uses the stored body. The eval script is the live model run.

## Suite setup

See the [root setup guide](../README.md) for installation and shared model settings. From the repository root, run `python run.py 3` using the virtual environment. Dashboards share the root `suite/` assets.
