"""Load handbook markdown into citable chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"\n(?=#+\s)")


META = re.compile(r"^meta:\s*(.+)$", re.IGNORECASE)
FIELD = re.compile(r"([a-z_]+)=([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    title: str
    text: str
    topic: str = ""
    status: str = "current"


def _meta(raw: str) -> tuple[dict[str, str], str]:
    fields: dict[str, str] = {}
    kept: list[str] = []
    for line in raw.splitlines():
        match = META.match(line.strip())
        if match:
            fields.update(dict(FIELD.findall(match.group(1))))
            continue
        kept.append(line)
    return fields, "\n".join(kept)


def load_chunks(directory: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise FileNotFoundError(
            f"No handbook markdown files in {directory}. Add .md files and restart."
        )
    for path in paths:
        fields, raw = _meta(path.read_text(encoding="utf-8"))
        status = fields.get("status", "current")
        if status not in {"current", "superseded"}:
            raise ValueError(f"{path.name} has status {status!r}. Use current or superseded.")
        topic = fields.get("topic", path.stem)
        sections = [part.strip() for part in HEADING.split(raw) if part.strip()]
        for index, section in enumerate(sections):
            title = section.splitlines()[0].lstrip("#").strip() or path.stem
            chunks.append(
                Chunk(
                    chunk_id=f"{path.stem}-{index}",
                    source=path.name,
                    title=title,
                    text=section,
                    topic=topic,
                    status=status,
                )
            )
    return chunks
