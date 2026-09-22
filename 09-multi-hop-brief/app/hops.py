"""A brief with a missing required hop is not allowed to state a number."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9$]+")


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    source: str
    text: str


@dataclass(frozen=True)
class Hop:
    question: str
    required: bool
    answer: str
    quote: str
    chunk_id: str
    supported: bool
    source: str
    hop_id: str = ""
    depends_on: list[str] = None
    status: str = ""  # "Verified" | "Missing Citation" | "Gated"
    start_char: int = 0
    end_char: int = 0

    def __post_init__(self) -> None:
        if self.depends_on is None:
            object.__setattr__(self, "depends_on", [])
        if not self.status:
            st = "Verified" if self.supported else "Missing Citation"
            object.__setattr__(self, "status", st)


@dataclass(frozen=True)
class Brief:
    refused: bool
    answer: str
    hops: list[Hop]
    reason: str
    graph: dict = None

    def __post_init__(self) -> None:
        if self.graph is None:
            object.__setattr__(self, "graph", {})


def load_passages(directory: Path) -> list[Passage]:
    passages: list[Passage] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            passages.append(Passage(chunk_id=path.stem, source=path.name, text=text))
    if not passages:
        raise FileNotFoundError(f"No passages in {directory}.")
    return passages


def find_quote_span(quote: str, text: str) -> tuple[int, int] | None:
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


def rank_passages(question: str, passages: list[Passage], k: int = 2) -> list[Passage]:
    wanted = set(TOKEN.findall(question.lower()))
    scored = sorted(
        passages,
        key=lambda passage: len(wanted & set(TOKEN.findall(passage.text.lower()))),
        reverse=True,
    )
    return scored[:k]


def bind_hop(
    question: str,
    required: bool,
    answer: str,
    quote: str,
    chunk_id: str,
    passages: list[Passage],
    hop_id: str = "",
    depends_on: list[str] | None = None,
) -> Hop:
    by_id = {passage.chunk_id: passage for passage in passages}
    passage = by_id.get(chunk_id)
    span = find_quote_span(quote, passage.text) if passage else None
    supported = passage is not None and span is not None
    start_char, end_char = (span[0], span[1]) if span else (0, 0)
    verbatim_quote = passage.text[start_char:end_char] if (passage and span) else ""
    status = "Verified" if supported else "Missing Citation"

    return Hop(
        question=question,
        required=required,
        answer=answer.strip() if supported else "",
        quote=verbatim_quote if supported else "",
        chunk_id=chunk_id if supported else "",
        supported=supported,
        source=passage.source if supported and passage else "",
        hop_id=hop_id,
        depends_on=list(depends_on or []),
        status=status,
        start_char=start_char,
        end_char=end_char,
    )


def evaluate_dag(hops: list[Hop]) -> tuple[list[Hop], dict]:
    """Evaluate DAG dependencies across hops.

    If any prerequisite hop is not 'Verified', dependent hops are marked 'Gated'
    and their conclusions are strictly withheld.
    """
    evaluated: list[Hop] = []
    status_by_id: dict[str, str] = {}
    nodes = []
    edges = []

    for idx, hop in enumerate(hops):
        hid = hop.hop_id or f"hop_{idx+1}"
        # Check prerequisite dependencies
        gated = False
        for dep in hop.depends_on:
            edges.append({"from": dep, "to": hid})
            if status_by_id.get(dep) != "Verified":
                gated = True

        if gated:
            new_hop = Hop(
                question=hop.question,
                required=hop.required,
                answer="",  # strictly withhold conclusion
                quote="",
                chunk_id="",
                supported=False,
                source=hop.source,
                hop_id=hid,
                depends_on=hop.depends_on,
                status="Gated",
                start_char=0,
                end_char=0,
            )
        else:
            new_hop = Hop(
                question=hop.question,
                required=hop.required,
                answer=hop.answer,
                quote=hop.quote,
                chunk_id=hop.chunk_id,
                supported=hop.supported,
                source=hop.source,
                hop_id=hid,
                depends_on=hop.depends_on,
                status=hop.status or ("Verified" if hop.supported else "Missing Citation"),
                start_char=hop.start_char,
                end_char=hop.end_char,
            )

        evaluated.append(new_hop)
        status_by_id[hid] = new_hop.status
        nodes.append({
            "id": hid,
            "label": new_hop.question,
            "status": new_hop.status,
            "source": new_hop.source,
            "quote": new_hop.quote,
            "answer": new_hop.answer,
            "required": new_hop.required,
            "depends_on": new_hop.depends_on,
        })

    # Synthesis node depends on all required hops
    all_required_verified = all(h.status == "Verified" for h in evaluated if h.required)
    synthesis_status = "Verified" if all_required_verified else "Gated"
    for h in evaluated:
        if h.required:
            edges.append({"from": h.hop_id or f"hop_{evaluated.index(h)+1}", "to": "synthesis"})

    nodes.append({
        "id": "synthesis",
        "label": "Final Synthesis",
        "status": synthesis_status,
        "depends_on": [h.hop_id or f"hop_{idx+1}" for idx, h in enumerate(evaluated) if h.required],
    })

    return evaluated, {"nodes": nodes, "edges": edges}


def compose(hops: list[Hop], answer: str, graph: dict | None = None) -> Brief:
    evaluated_hops, dag_graph = evaluate_dag(hops)
    final_graph = graph or dag_graph

    missing = [hop.question for hop in evaluated_hops if hop.required and not hop.supported]
    if missing:
        joined = "; ".join(missing)
        return Brief(
            refused=True,
            answer="",
            hops=evaluated_hops,
            reason=f"Refusing to state a result. These required hops have no verbatim support: {joined}.",
            graph=final_graph,
        )
    if not answer.strip():
        return Brief(refused=True, answer="", hops=evaluated_hops, reason="The synthesis was empty.", graph=final_graph)
    return Brief(refused=False, answer=answer.strip(), hops=evaluated_hops, reason="", graph=final_graph)
