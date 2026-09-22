import json
from pathlib import Path

import pytest

from app.extract import invoice_path
from app.match import match_invoice
from app.review import Extraction, FieldScore, Invoice, LineItem, prepare, review_reasons
from app.store import add_review, connect, resolve

INVOICES = Path(__file__).resolve().parents[1] / "data" / "invoices"


def _confident(invoice: Invoice) -> Extraction:
    fields = [
        FieldScore(field=name, confidence=0.95)
        for name in ("vendor", "invoice_number", "invoice_date", "total")
    ]
    return prepare(Extraction(invoice=invoice, fields=fields))


def test_consistent_invoice_needs_no_review():
    invoice = Invoice(
        vendor="Northwind Supply",
        invoice_number="INV-1001",
        invoice_date="2026-03-12",
        line_items=[
            LineItem(description="Widget", quantity=2, unit_price=50, amount=100),
            LineItem(description="Gadget", quantity=1, unit_price=250, amount=250),
        ],
        subtotal=350,
        tax=28,
        total=378,
    )
    assert review_reasons(_confident(invoice)) == []


def test_printed_total_mismatch_is_queued_even_when_confidence_is_high():
    invoice = Invoice(
        vendor="Pixel Parts",
        invoice_number="INV-3090",
        invoice_date="2026-05-02",
        line_items=[LineItem(description="Cable", quantity=2, unit_price=25, amount=50)],
        subtotal=100,
        tax=0,
        total=150,
    )
    reasons = review_reasons(_confident(invoice))
    assert any("printed total" in reason for reason in reasons)


def test_percent_style_confidence_is_scaled():
    extraction = prepare(Extraction(fields=[FieldScore(field="total", confidence=80)]))
    assert extraction.fields[0].confidence == pytest.approx(0.8)


def test_price_variance_is_a_review_reason_even_when_the_invoice_adds_up():
    invoice = Invoice(
        vendor="Pixel Parts",
        invoice_number="INV-3090",
        po_number="PO-3090",
        line_items=[LineItem(description="Cable", quantity=2, unit_price=25, amount=50)],
        subtotal=50,
        tax=0,
        total=50,
    )
    reasons = match_invoice(
        invoice,
        {"PO-3090": {"vendor": "Pixel Parts", "lines": [{"description": "Cable", "quantity": 2, "unit_price": 20}]}},
    )
    assert any(reason.startswith("PRICE_VARIANCE") for reason in reasons)


def test_missing_purchase_order_cannot_auto_clear():
    reasons = match_invoice(Invoice(vendor="Northwind Supply", po_number=""), {})
    assert reasons[0].startswith("NO_PO")


def test_document_id_cannot_escape_the_invoice_directory():
    with pytest.raises(ValueError):
        invoice_path(INVOICES, "../llm.py")
    with pytest.raises((ValueError, FileNotFoundError)):
        invoice_path(INVOICES, "missing.txt")
    path = invoice_path(INVOICES, "northwind-1001.txt")
    assert path.name == "northwind-1001.txt"


def test_resolve_uses_the_stored_row_and_rejects_a_second_decision(tmp_path):
    conn = connect(tmp_path / "reviews.db")
    review_id = add_review(
        conn,
        "mismatch-3090.txt",
        _confident(Invoice(vendor="Pixel Parts", total=150, subtotal=100)),
        ["Subtotal plus tax is 100.00, but the printed total is 150.00."],
    )
    resolved = resolve(conn, review_id, "accept", "Arithmetic was a scan error. Paid 100.")
    assert resolved["status"] == "accepted"
    assert resolved["invoice"]["vendor"] == "Pixel Parts"
    with pytest.raises(ValueError):
        resolve(conn, review_id, "reject", "again")
    conn.close()
    assert json.dumps({"ok": True})


def test_arithmetic_reconciler_line_item_sum_mismatch():
    invoice = Invoice(
        vendor="Test Corp",
        invoice_number="INV-001",
        invoice_date="2026-03-01",
        line_items=[
            LineItem(description="Item A", quantity=2, unit_price=20, amount=40),
            LineItem(description="Item B", quantity=1, unit_price=30, amount=30),
        ],
        subtotal=80,  # Line items sum to 70, not 80
        tax=0,
        total=80,
    )
    reasons = review_reasons(_confident(invoice))
    assert any("Line items sum to 70.00" in r for r in reasons)


def test_arithmetic_reconciler_tax_rate_mismatch():
    invoice = Invoice(
        vendor="Test Corp",
        invoice_number="INV-002",
        invoice_date="2026-03-01",
        line_items=[LineItem(description="Item A", quantity=1, unit_price=100, amount=100)],
        subtotal=100,
        tax_rate=10.0,  # 10% on 100 should be 10.00
        tax=15.00,      # Discrepancy!
        total=115,
    )
    reasons = review_reasons(_confident(invoice))
    assert any("Tax rate" in r and "mismatch" or "printed tax is 15.00" in r for r in reasons)


def test_arithmetic_reconciler_total_with_discount():
    invoice = Invoice(
        vendor="Test Corp",
        invoice_number="INV-003",
        invoice_date="2026-03-01",
        line_items=[LineItem(description="Item A", quantity=1, unit_price=100, amount=100)],
        subtotal=100,
        tax=10,
        discount=15,
        total=95,  # 100 + 10 - 15 = 95
    )
    assert review_reasons(_confident(invoice)) == []

    # Discrepancy > 0.01
    bad_invoice = invoice.model_copy(update={"total": 96})
    reasons = review_reasons(_confident(bad_invoice))
    assert any("printed total is 96.00" in r for r in reasons)


def test_confidence_threshold_85_flags_awaiting_human_triage(tmp_path):
    conn = connect(tmp_path / "reviews_thresh.db")
    invoice = Invoice(
        vendor="Test Corp",
        invoice_number="INV-004",
        invoice_date="2026-03-01",
        subtotal=100,
        tax=0,
        total=100,
    )
    # Field confidence 0.84 is below 0.85 threshold
    fields = [
        FieldScore(field="vendor", confidence=0.84),
        FieldScore(field="invoice_number", confidence=0.95),
        FieldScore(field="invoice_date", confidence=0.95),
        FieldScore(field="total", confidence=0.95),
    ]
    extraction = prepare(Extraction(invoice=invoice, fields=fields))
    reasons = review_reasons(extraction)
    assert any("vendor confidence 0.84 is below 0.85" in r for r in reasons)
    
    review_id = add_review(conn, "test-doc.txt", extraction, reasons)
    from app.store import list_reviews
    reviews = list_reviews(conn)
    assert reviews[0]["status"] == "AWAITING_HUMAN_TRIAGE"
    conn.close()


def test_operator_manual_edit_and_approve_flow(tmp_path):
    from app.store import edit_review, resolve
    conn = connect(tmp_path / "reviews_edit.db")
    # Pixel Parts mismatch: total is 150 but subtotal is 100
    invoice = Invoice(
        vendor="Pixel Parts",
        invoice_number="INV-3090",
        invoice_date="2026-05-02",
        line_items=[
            LineItem(description="Cable", quantity=2, unit_price=25, amount=50),
            LineItem(description="Adapter", quantity=1, unit_price=50, amount=50),
        ],
        subtotal=100,
        tax=0,
        total=150,
    )
    extraction = _confident(invoice)
    reasons = review_reasons(extraction)
    review_id = add_review(conn, "mismatch-3090.txt", extraction, reasons)
    
    # Operator corrects the total from 150 to 100
    updated = edit_review(conn, review_id, {"total": 100}, note="Corrected typo in printed total")
    assert updated["status"] == "accepted"
    assert updated["reasons"] == []
    assert updated["invoice"]["total"] == 100
    conn.close()

