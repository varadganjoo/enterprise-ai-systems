"""Verdicts are computed from evidence. The model's suggested label is not used."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

META = re.compile(r"^meta:\s*(.+)$", re.IGNORECASE)
FIELD = re.compile(r"([a-z_]+)=([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class Source:
    chunk_id: str
    source: str
    topic: str
    status: str
    text: str


@dataclass(frozen=True)
class Claim:
    text: str
    quote: str
    chunk_id: str


class VerdictStr(str):
    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.lower() == other.lower()
        return super().__eq__(other)

    def __hash__(self) -> int:
        return hash(self.lower())


class Verdict:
    SUPPORTED = VerdictStr("supported")
    CONTRADICTED = VerdictStr("contradicted")
    SUPERSEDED = VerdictStr("superseded")
    UNVERIFIABLE = VerdictStr("unverifiable")


@dataclass(frozen=True)
class Finding:
    text: str
    verdict: str
    quote: str
    source: str
    reason: str
    start_char: int = 0
    end_char: int = 0
    confidence: float = 1.0


def load_sources(directory: Path) -> list[Source]:
    sources: list[Source] = []
    for path in sorted(directory.glob("*.md")):
        fields: dict[str, str] = {}
        lines: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = META.match(line.strip())
            if match:
                fields.update(dict(FIELD.findall(match.group(1))))
                continue
            lines.append(line)
        text = "\n".join(lines).strip()
        status = fields.get("status", "current")
        if status not in {"current", "superseded"}:
            raise ValueError(f"{path.name} has status {status!r}. Use current or superseded.")
        sources.append(
            Source(
                chunk_id=path.stem,
                source=path.name,
                topic=fields.get("topic", path.stem),
                status=status,
                text=text,
            )
        )
    if not sources:
        raise FileNotFoundError(f"No source markdown in {directory}.")
    return sources


def find_quote_span(quote: str, text: str) -> tuple[int, int] | None:
    """Find exact character-level offsets [start_char, end_char] of quote in text."""
    cleaned = " ".join(quote.split())
    if len(cleaned) < 8:
        return None
    pos = text.find(quote)
    if pos != -1:
        return (pos, pos + len(quote))
    pos = text.find(cleaned)
    if pos != -1:
        return (pos, pos + len(cleaned))
    tokens = quote.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    match = re.search(pattern, text)
    if match:
        return (match.start(), match.end())
    return None


def _contains(quote: str, text: str) -> bool:
    return find_quote_span(quote, text) is not None


def adjudicate(claims: list[Claim], sources: list[Source]) -> list[Finding]:
    by_id = {source.chunk_id: source for source in sources}
    current_topics = {source.topic for source in sources if source.status == "current"}
    findings: list[Finding] = []
    for claim in claims:
        source = by_id.get(claim.chunk_id)
        span = find_quote_span(claim.quote, source.text) if source else None

        # Case 1: Unverifiable (no source found or quote not in source)
        if source is None or span is None:
            findings.append(
                Finding(
                    text=claim.text,
                    verdict=Verdict.UNVERIFIABLE,
                    quote="",
                    source="",
                    reason="No verbatim span in the named source supports this claim.",
                    start_char=0,
                    end_char=0,
                    confidence=0.0,
                )
            )
            continue

        start_char, end_char = span
        verbatim_quote = source.text[start_char:end_char]

        # Case 2: Source is superseded
        if source.status == "superseded":
            if source.topic in current_topics:
                current = next(item.source for item in sources if item.topic == source.topic and item.status == "current")
                claim_lower = claim.text.lower()
                # If claim asserts it is "current", it directly contradicts governing policy
                if any(w in claim_lower for w in ("current", "currently", "now", "today", "active")):
                    findings.append(
                        Finding(
                            text=claim.text,
                            verdict=Verdict.CONTRADICTED,
                            quote=verbatim_quote,
                            source=source.source,
                            reason=f"The claim asserts this is current, but {source.source} is superseded. The governing file is {current}.",
                            start_char=start_char,
                            end_char=end_char,
                            confidence=0.98,
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            text=claim.text,
                            verdict=Verdict.SUPERSEDED,
                            quote=verbatim_quote,
                            source=source.source,
                            reason=f"The quote is from superseded {source.source}. The governing file is {current}.",
                            start_char=start_char,
                            end_char=end_char,
                            confidence=0.95,
                        )
                    )
            else:
                findings.append(
                    Finding(
                        text=claim.text,
                        verdict=Verdict.SUPERSEDED,
                        quote=verbatim_quote,
                        source=source.source,
                        reason=f"The quote is from a superseded source ({source.source}) with no active replacement.",
                        start_char=start_char,
                        end_char=end_char,
                        confidence=0.90,
                    )
                )
            continue

        # Case 3: Source is current -> SUPPORTED
        findings.append(
            Finding(
                text=claim.text,
                verdict=Verdict.SUPPORTED,
                quote=verbatim_quote,
                source=source.source,
                reason="The quote is a verbatim span of a current governing source.",
                start_char=start_char,
                end_char=end_char,
                confidence=1.0,
            )
        )
    return findings
