"""Score extracted invoices against the golden file. Requires GEMINI_API_KEY."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.extract import extract_document, invoice_path  # noqa: E402
from app.llm import STRONG_MODEL, get_client  # noqa: E402
from app.review import review_reasons  # noqa: E402

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y")


def vendor_key(value: str) -> str:
    folded = value.casefold().replace("1", "i").replace("0", "o")
    return re.sub(r"[^a-z0-9]", "", folded)


def invoice_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def parse_date(value: str) -> str:
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def main() -> None:
    cases = json.loads((ROOT / "evals" / "gold.json").read_text(encoding="utf-8"))
    client = get_client()
    field_hits = 0
    field_total = 0
    review_hits = 0
    for case in cases:
        text = invoice_path(ROOT / "data" / "invoices", case["document"]).read_text(encoding="utf-8")
        extraction, prompt_tokens, output_tokens = extract_document(client, text)
        invoice = extraction.invoice
        reasons = review_reasons(extraction)
        needs_review = bool(reasons)
        checks = {
            "vendor": vendor_key(invoice.vendor) == vendor_key(case["vendor"]),
            "invoice_number": invoice_key(invoice.invoice_number) == invoice_key(case["invoice_number"]),
            "invoice_date": parse_date(invoice.invoice_date) == case["invoice_date"],
            "total": abs(float(invoice.total) - float(case["total"])) <= 0.01,
        }
        field_hits += sum(checks.values())
        field_total += len(checks)
        review_ok = needs_review == case["expect_review"]
        review_hits += int(review_ok)
        print(
            f"{case['document']:22} fields={sum(checks.values())}/4 "
            f"review={needs_review} expected_review={case['expect_review']} "
            f"tokens={prompt_tokens}+{output_tokens}"
        )
        if not all(checks.values()):
            print("  misses", [name for name, ok in checks.items() if not ok], invoice.model_dump())
    print("---")
    print(f"field_accuracy {field_hits}/{field_total}")
    print(f"review_routing {review_hits}/{len(cases)}")
    print(f"model {STRONG_MODEL}")


if __name__ == "__main__":
    main()
