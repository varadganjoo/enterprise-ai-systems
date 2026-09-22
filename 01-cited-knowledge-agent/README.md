# Cited knowledge agent

A question about the current policy cannot be answered from a superseded file. A question that names 2024 still can. When both versions are retrieved, the response includes that conflict.

Answers over a company handbook that contains a real conflict: the 2024 PTO policy says 15 days, and the current 2026 policy says 20. Every non-refusal ships with a quote that is checked, in code, to be a verbatim span of a retrieved chunk. A quote the model invented is dropped. If nothing remains, the answer is refused.

Retrieval is BM25 plus Gemini embeddings (`gemini-embedding-001`, 768 dimensions), fused with reciprocal rank fusion. The answer model is `gemini-3.8-flash`. No other API key is required.

## Run

From this directory, with the repo virtualenv:

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8001
```

Open http://127.0.0.1:8001

Ask "How many PTO days does a full-time employee get under the current policy?" The citation should come from `pto-2026.md`. Ask "What is the capital of France?" The handbook does not contain that, so the answer is a refusal.

## Eval

```powershell
..\.venv\Scripts\python evals\run_eval.py
```

The scorecard reports retrieval hit rate, grounded answer rate, verbatim citation rate, refusal accuracy, mean latency, and token totals. Unit tests cover fusion, verbatim checking, and the refusal that follows a bad quote:

```powershell
..\.venv\Scripts\python -m pytest
```

## What a client is looking at

The failure mode is a fluent answer that cites the superseded policy, or a quote that never appeared in the file. The check that matters is in `app/grounding.py`: citations that are not substrings of the retrieved chunk are discarded before the response is returned.
