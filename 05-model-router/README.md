# Model router

An easy, confident task is answered by the cheap model and then checked. If that check is weak, the same task is answered again by the strong model. Hard tasks go straight to the strong model.

A cheap grader (`gemini-3.5-flash-lite`) labels a task easy or hard and gives a confidence. Easy and at least 0.80 goes to Flash-Lite. Hard tasks, and easy tasks below 0.80, go to `gemini-3.8-flash`.

The cost field multiplies measured tokens by rates in `app/router.py`. Those rates are illustrative. Replace them with the current Gemini price sheet before you quote a number to a client. The token counts are the measurement.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8005
```

Open http://127.0.0.1:8005. The default shirt-discount question is the hard case: 40 discounted 25 percent is 30, plus 8 percent tax is 32.40.

```powershell
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\python evals\run_eval.py
```

The eval runs each golden task three ways: always cheap, always strong, and routed. It prints answer accuracy and token totals for each way.
