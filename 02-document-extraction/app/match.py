"""Compare an invoice with the purchase order it names."""

from __future__ import annotations

import re

from app.review import Invoice, LineItem

TOLERANCE = 0.02


def _key(value: str) -> str:
    folded = value.casefold().replace("1", "i").replace("0", "o")
    return re.sub(r"[^a-z0-9]", "", folded)


def _find_line(line: LineItem, po_lines: list[dict]) -> dict | None:
    wanted = _key(line.description)
    if not wanted:
        return None
    for candidate in po_lines:
        name = _key(str(candidate.get("description", "")))
        if name and (name in wanted or wanted in name):
            return candidate
    return None


def match_invoice(invoice: Invoice, purchase_orders: dict) -> list[str]:
    po_id = invoice.po_number.strip().upper()
    if not po_id:
        return ["NO_PO: the invoice has no purchase order number."]
    order = purchase_orders.get(po_id)
    if order is None:
        return [f"UNKNOWN_PO: {po_id} is not in the purchase-order book."]
    reasons: list[str] = []
    if _key(invoice.vendor) != _key(str(order.get("vendor", ""))):
        reasons.append(
            f"VENDOR_MISMATCH: invoice vendor {invoice.vendor!r} does not match {po_id} vendor {order.get('vendor')!r}."
        )
    po_lines = list(order.get("lines", []))
    for line in invoice.line_items:
        partner = _find_line(line, po_lines)
        if partner is None:
            reasons.append(f"UNORDERED_LINE: {line.description!r} is not on {po_id}.")
            continue
        if abs(float(line.unit_price) - float(partner["unit_price"])) > TOLERANCE:
            reasons.append(
                f"PRICE_VARIANCE: {line.description} is {line.unit_price} on the invoice and {partner['unit_price']} on {po_id}."
            )
        if abs(float(line.quantity) - float(partner["quantity"])) > 0.001:
            reasons.append(
                f"QTY_VARIANCE: {line.description} quantity is {line.quantity} on the invoice and {partner['quantity']} on {po_id}."
            )
    return reasons
