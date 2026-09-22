# Operator agent

Outbound text that says a refund or payment already happened is rejected before it is stored. Queueing the same body twice returns the existing approval.

A support agent with six tools. `propose_send` inserts a pending approval and leaves the ticket open. The approve endpoint sends the body stored on that approval row. A second decision is rejected. The loop stops at 6 steps or 12,000 tokens.

The model is `gemini-3.8-flash`. No other API key is required.

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
