"""A superseded policy cannot support a current-state answer unless the question asks for history."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.corpus import Chunk
from app.retrieve import Hit

HISTORICAL = re.compile(
    r"\b(2024|superseded|previous|prior policy|old policy|used to|historically)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Conflict:
    topic: str
    current_source: str
    superseded_source: str


def asks_for_history(question: str) -> bool:
    return bool(HISTORICAL.search(question or ""))


def conflicts_in(chunks: list[Chunk]) -> list[Conflict]:
    by_topic: dict[str, dict[str, str]] = {}
    for chunk in chunks:
        if not chunk.topic:
            continue
        by_topic.setdefault(chunk.topic, {})[chunk.status] = chunk.source
    found: list[Conflict] = []
    for topic, versions in sorted(by_topic.items()):
        if "current" in versions and "superseded" in versions:
            found.append(
                Conflict(
                    topic=topic,
                    current_source=versions["current"],
                    superseded_source=versions["superseded"],
                )
            )
    return found


def conflicts_in_hits(hits: list[Hit]) -> list[Conflict]:
    return conflicts_in([hit.chunk for hit in hits])
