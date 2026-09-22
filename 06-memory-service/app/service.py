"""PII Tokenizer / Redaction Engine and Memory Service Layer.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.store import (
    add_memory,
    forget_memories,
    get_active_slots,
    get_history_timeline,
    list_memories,
    supersede_memory,
)

# Robust PII Patterns
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b")
PHONE_RE = re.compile(
    r"\b(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b"
)
SSN_RE = re.compile(r"\b(?:\d{3}-\d{2}-\d{4}|\b\d{9}\b)")
CREDIT_CARD_RE = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b|\b\d{15,16}\b")
SENSITIVE_SECRET = re.compile(r"\b(password|secret key|api[_-]?key|private[_-]?key|cvv)\b", re.IGNORECASE)


@dataclass
class RedactionResult:
    redacted_text: str
    vault: dict[str, str] = field(default_factory=dict)
    redactions: list[dict[str, str]] = field(default_factory=list)


class PIITokenizer:
    """Scans and masks sensitive PII (credit cards, SSNs, emails, phone numbers)
    with placeholder tokens before sending to LLM, and provides bidirectional re-hydration."""

    @classmethod
    def contains_secret(cls, text: str) -> bool:
        """Returns True if text contains explicit secrets like passwords or API keys."""
        return bool(SENSITIVE_SECRET.search(text or ""))

    @classmethod
    def contains_pii(cls, text: str) -> bool:
        """Returns True if any PII pattern is matched."""
        if not text:
            return False
        return bool(
            EMAIL_RE.search(text)
            or PHONE_RE.search(text)
            or SSN_RE.search(text)
            or CREDIT_CARD_RE.search(text)
        )

    @classmethod
    def tokenize(cls, text: str) -> RedactionResult:
        """Scans and masks PII with deterministic placeholder tokens e.g. [EMAIL_1], [PHONE_1].
        Returns RedactionResult with redacted text, vault dictionary, and metadata."""
        if not text:
            return RedactionResult(redacted_text="")

        vault: dict[str, str] = {}
        redactions: list[dict[str, str]] = []
        counts: dict[str, int] = {
            "EMAIL": 0,
            "PHONE": 0,
            "SSN": 0,
            "CREDIT_CARD": 0,
        }

        def _mask(match: re.Match, pii_type: str) -> str:
            raw_val = match.group(0)
            # Avoid re-tokenizing if already matched or duplicate within same text
            for tok, orig in vault.items():
                if orig == raw_val and tok.startswith(f"[{pii_type}_"):
                    return tok

            counts[pii_type] += 1
            token = f"[{pii_type}_{counts[pii_type]}]"
            vault[token] = raw_val
            redactions.append({
                "token": token,
                "type": pii_type,
                "original": raw_val,
            })
            return token

        # Redact in order of specificity
        redacted = SSN_RE.sub(lambda m: _mask(m, "SSN"), text)
        redacted = CREDIT_CARD_RE.sub(lambda m: _mask(m, "CREDIT_CARD"), redacted)
        redacted = EMAIL_RE.sub(lambda m: _mask(m, "EMAIL"), redacted)
        redacted = PHONE_RE.sub(lambda m: _mask(m, "PHONE"), redacted)

        return RedactionResult(
            redacted_text=redacted,
            vault=vault,
            redactions=redactions,
        )

    @classmethod
    def rehydrate(cls, text: str, vault: dict[str, str]) -> str:
        """Restores original PII values from tokens in assistant responses."""
        if not text or not vault:
            return text or ""
        restored = text
        for token, original in vault.items():
            restored = restored.replace(token, original)
        return restored


def get_active_memory_context(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    redact_pii: bool = True,
) -> dict[str, Any]:
    """Retrieves active memory context for the session with optional PII protection."""
    active_rows = get_active_slots(conn, session_id)
    rendered_items = []
    vault: dict[str, str] = {}

    for row in active_rows:
        content = row["content"]
        if redact_pii:
            redaction = PIITokenizer.tokenize(content)
            content = redaction.redacted_text
            vault.update(redaction.vault)
        rendered_items.append({
            "id": row["id"],
            "slot": row["slot"] or row["kind"],
            "content": content,
            "created_at": row["created_at"],
        })

    if not rendered_items:
        context_str = "No active memories recorded for this session."
    else:
        context_str = "Active session memories:\n" + "\n".join(
            f"- [{item['slot']}]: {item['content']} (id: {item['id']})"
            for item in rendered_items
        )

    return {
        "session_id": session_id,
        "context": context_str,
        "active_slots": rendered_items,
        "pii_protected": redact_pii,
        "vault": vault,
    }
