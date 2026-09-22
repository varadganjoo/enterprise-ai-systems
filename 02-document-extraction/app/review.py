"""Decide whether an extraction can be accepted without a person."""

from __future__ import annotations

from pydantic import BaseModel, Field

THRESHOLD = 0.85
TOLERANCE = 0.01
WATCHED = ("vendor", "invoice_number", "invoice_date", "total")


class LineItem(BaseModel):
    description: str = ""
    quantity: float = 0
    unit_price: float = 0
    amount: float = 0


class Invoice(BaseModel):
    vendor: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    po_number: str = ""
    currency: str = "USD"
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float = 0
    tax: float = 0
    tax_rate: float = 0
    discount: float = 0
    total: float = 0


class FieldScore(BaseModel):
    field: str = ""
    confidence: float = 0
    note: str = ""


class Extraction(BaseModel):
    invoice: Invoice = Field(default_factory=Invoice)
    fields: list[FieldScore] = Field(default_factory=list)


def normalize_confidence(value: float) -> float:
    if value > 1 and value <= 100:
        value = value / 100
    return min(1.0, max(0.0, value))


def prepare(extraction: Extraction) -> Extraction:
    fields = [
        field.model_copy(update={"confidence": normalize_confidence(field.confidence)})
        for field in extraction.fields
    ]
    return extraction.model_copy(update={"fields": fields})


def reconcile_invoice(invoice: Invoice, tolerance: float = TOLERANCE) -> dict:
    discrepancies: list[str] = []

    # 1. Line-item extension: quantity * unit_price == amount
    line_items_valid = True
    calc_line_sum = 0.0
    for idx, item in enumerate(invoice.line_items, start=1):
        expected_amount = round(float(item.quantity) * float(item.unit_price), 2)
        calc_line_sum += expected_amount
        if item.amount > 0 and abs(expected_amount - float(item.amount)) > tolerance:
            line_items_valid = False
            discrepancies.append(
                f"Line item {idx} ({item.description!r}): quantity ({item.quantity}) * unit_price ({item.unit_price:.2f}) = {expected_amount:.2f}, but amount is {item.amount:.2f}."
            )

    # 2. Line-item sum vs subtotal
    # If line items are present, check sum against subtotal
    if invoice.line_items:
        line_sum_to_check = calc_line_sum if calc_line_sum > 0 else sum(item.amount for item in invoice.line_items)
        line_sum_to_check = round(line_sum_to_check, 2)
        if abs(line_sum_to_check - float(invoice.subtotal)) > tolerance:
            line_items_valid = False
            discrepancies.append(
                f"Line items sum to {line_sum_to_check:.2f}, but the subtotal is {invoice.subtotal:.2f}."
            )
    else:
        line_sum_to_check = float(invoice.subtotal)

    # 3. Tax calculation: subtotal * tax_rate ~= tax
    tax_valid = True
    expected_tax = float(invoice.tax)
    if float(invoice.tax_rate) > 0:
        effective_rate = float(invoice.tax_rate) / 100.0 if float(invoice.tax_rate) > 1.0 else float(invoice.tax_rate)
        expected_tax = round(float(invoice.subtotal) * effective_rate, 2)
        if abs(expected_tax - float(invoice.tax)) > tolerance:
            tax_valid = False
            discrepancies.append(
                f"Tax rate ({invoice.tax_rate}%) on subtotal ({invoice.subtotal:.2f}) is {expected_tax:.2f}, but printed tax is {invoice.tax:.2f}."
            )

    # 4. Total calculation: subtotal + tax - discount == total
    expected_total = round(float(invoice.subtotal) + float(invoice.tax) - float(invoice.discount), 2)
    total_valid = abs(expected_total - float(invoice.total)) <= tolerance
    if not total_valid:
        if float(invoice.discount) > 0:
            discrepancies.append(
                f"Subtotal ({invoice.subtotal:.2f}) plus tax ({invoice.tax:.2f}) minus discount ({invoice.discount:.2f}) is {expected_total:.2f}, but the printed total is {invoice.total:.2f}."
            )
        else:
            discrepancies.append(
                f"Subtotal plus tax is {expected_total:.2f}, but the printed total is {invoice.total:.2f}."
            )

    return {
        "valid": line_items_valid and tax_valid and total_valid,
        "line_items_valid": line_items_valid,
        "line_items_sum": line_sum_to_check,
        "subtotal": float(invoice.subtotal),
        "tax_valid": tax_valid,
        "tax_rate": float(invoice.tax_rate),
        "expected_tax": expected_tax,
        "actual_tax": float(invoice.tax),
        "discount": float(invoice.discount),
        "total_valid": total_valid,
        "expected_total": expected_total,
        "actual_total": float(invoice.total),
        "discrepancies": discrepancies,
    }


def review_reasons(extraction: Extraction, purchase_orders: dict | None = None) -> list[str]:
    reasons: list[str] = []
    scores = {field.field: field.confidence for field in extraction.fields}
    for name in WATCHED:
        score = scores.get(name)
        if score is None:
            reasons.append(f"{name} has no confidence score.")
        elif score < THRESHOLD:
            reasons.append(f"{name} confidence {score:.2f} is below {THRESHOLD:.2f}.")

    # Arithmetic reconciliation
    reconciliation = reconcile_invoice(extraction.invoice)
    reasons.extend(reconciliation["discrepancies"])

    if purchase_orders is not None:
        from app.match import match_invoice

        reasons.extend(match_invoice(extraction.invoice, purchase_orders))
    return reasons
