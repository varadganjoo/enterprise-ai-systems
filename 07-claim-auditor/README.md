# Claim auditor

Someone else's draft is split into claims. A claim is **supported** only when its quote is a verbatim span of a current source. The same quote from the superseded 2024 PTO policy is **contradicted**, because a current policy exists for that topic. A quote that is not in the named source is **unverifiable**. The model picks the quote. It does not pick the verdict.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8007
```

Open http://127.0.0.1:8007 and paste a draft that says the current policy is 15 days and also 20 days.

```powershell
..\.venv\Scripts\python -m pytest
```
