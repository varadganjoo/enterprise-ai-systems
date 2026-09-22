"""Outbound text cannot claim a refund or payment the tools are unable to perform."""

from __future__ import annotations

import re

COMPLETED_CLAIM = re.compile(
    r"\b("
    r"processed a refund|refund has been|refund was|have refunded|was refunded|"
    r"payment (was|has been) (sent|completed|issued)|"
    r"we have (issued|processed|completed) (a |the )?(refund|payment|credit)|"
    r"already (refunded|paid|credited)"
    r")\b",
    re.IGNORECASE,
)

UNAUTHORIZED_COMMITMENT = re.compile(
    r"\b("
    r"we (agree|promise|guarantee) to (pay|refund|compensate|settle)|"
    r"settlement agreement|legally binding|contractual obligation"
    r")\b",
    re.IGNORECASE,
)

PII_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PII_CREDIT_CARD = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b")

CREDENTIAL_API_KEY = re.compile(
    r"\b(sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[a-zA-Z0-9]{36}|Bearer\s+[a-zA-Z0-9_\-\.]{20,})\b"
)
CREDENTIAL_PLAINTEXT = re.compile(
    r"\b(password\s*[:=]\s*\S+|client_secret\s*[:=]\s*\S+|private_key\s*[:=]\s*\S+)\b",
    re.IGNORECASE,
)

ABUSIVE_LANGUAGE = re.compile(
    r"\b(idiot|stupid|shut up|moron|incompetent|fool|hate you|jerk|harass|worthless|scam artist)\b",
    re.IGNORECASE,
)


def outbound_violations(body: str) -> list[str]:
    text = body or ""
    violations: list[str] = []

    if COMPLETED_CLAIM.search(text):
        violations.append(
            "POLICY_BLOCK: the message says a refund or payment already happened. "
            "No tool can do that, so the text was not stored."
        )

    if UNAUTHORIZED_COMMITMENT.search(text):
        violations.append(
            "POLICY_BLOCK: the message makes an unauthorized legal or financial commitment. "
            "No tool is authorized to bind the company."
        )

    if PII_SSN.search(text) or PII_CREDIT_CARD.search(text):
        violations.append(
            "POLICY_BLOCK: the message contains sensitive PII (Social Security Number or Credit Card Number). "
            "Redact sensitive data before proceeding."
        )

    if CREDENTIAL_API_KEY.search(text) or CREDENTIAL_PLAINTEXT.search(text):
        violations.append(
            "POLICY_BLOCK: the message contains exposed credentials or secret tokens. "
            "Drafts must never leak credentials."
        )

    if ABUSIVE_LANGUAGE.search(text):
        violations.append(
            "POLICY_BLOCK: the message contains abusive or hostile sentiment. "
            "Drafts must adhere to professional communication standards."
        )

    return violations
