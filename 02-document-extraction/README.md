# Document extraction

Each invoice is matched to a purchase order. A unit price that disagrees with the order is a review reason even when the invoice's own arithmetic is consistent. A missing purchase-order number cannot clear on its own.

Four invoices, one of them with a printed total that does not match the lines. The model copies the page. Code then checks two things a client actually cares about: confidence on vendor, invoice number, date, and total, and whether the line items, subtotal, tax, and total agree within two cents. Anything that fails waits in a review queue. Accepting a review updates that stored row. The browser cannot submit a different invoice and have it treated as the extracted one.

The model is `gemini-3.8-flash`. No other API key is required.

## Run

```powershell
..\.venv\Scripts\python -m uvicorn app.main:app --port 8002
```

Open http://127.0.0.1:8002 and extract `mismatch-3090.txt`. The lines sum to 100 and the page says 150, so it should land in the queue even if every field confidence is high.

## Eval

```powershell
..\.venv\Scripts\python -m pytest
..\.venv\Scripts\python evals\run_eval.py
```

Field accuracy normalizes OCR confusions such as `BR1GHT` versus `Bright` for the vendor only. The review-routing score is separate: the broken invoice is supposed to be queued, and the consistent ones are supposed to be accepted.
