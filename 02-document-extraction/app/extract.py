"""Load an invoice file by id, with no path traversal."""

from __future__ import annotations

from pathlib import Path

from app.llm import STRONG_MODEL, generate_model
from app.review import Extraction, prepare

SYSTEM = (
    "Extract the invoice exactly as printed. "
    "Use YYYY-MM-DD for invoice_date. "
    "Put confidence between 0 and 1 on fields named vendor, invoice_number, invoice_date, and total. "
    "po_number is the purchase order id printed on the page, such as PO-1001. "
    "Copy the printed total even when the line items do not add up. "
    "Do not invent a vendor or an invoice number that is not on the page."
)


def invoice_path(directory: Path, document_id: str) -> Path:
    if (
        not document_id
        or document_id != Path(document_id).name
        or "/" in document_id
        or "\\" in document_id
        or ".." in document_id
    ):
        raise ValueError(f"Unknown document id {document_id!r}.")
    root = directory.resolve()
    path = (root / document_id).resolve()
    if path.parent != root or path.suffix.lower() != ".txt" or not path.is_file():
        raise FileNotFoundError(f"Unknown document id {document_id!r}.")
    return path


def list_documents(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.txt"))


def extract_document(client, text: str) -> tuple[Extraction, int, int]:
    draft, usage = generate_model(
        client,
        model=STRONG_MODEL,
        system=SYSTEM,
        prompt=text,
        schema=Extraction,
    )
    return prepare(draft), usage.prompt_tokens, usage.output_tokens
