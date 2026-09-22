# Multi-hop brief

The cancellation fee is not in one document. The contract says how many months remain and that the fee is the monthly rate times those months. The fee schedule says the rate is $400. Cancelling at the start of month 5 leaves two months, so the fee is $800.

Each hop must carry a verbatim quote. If a required hop does not, the brief is refused and the answer field is empty. The synthesis model is only called after that gate passes.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8009
```

Open http://127.0.0.1:8009 and ask what the cancellation fee is at the start of month 5.

```powershell
..\.venv\Scripts\python -m pytest
```
