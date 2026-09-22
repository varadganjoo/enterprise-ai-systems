from pathlib import Path

from app.corpus import Chunk, load_chunks
from app.grounding import CitationDraft, DraftAnswer, quote_in_chunk, verify
from app.retrieve import Hit, Index, reciprocal_rank_fusion

ROOT = Path(__file__).resolve().parents[1]


def test_handbook_contains_both_pto_policies():
    chunks = load_chunks(ROOT / "data" / "handbook")
    by_source = "\n".join(chunk.text for chunk in chunks)
    assert "15 days" in by_source
    assert "20 days" in by_source
    sources = {chunk.source for chunk in chunks}
    assert "pto-2024.md" in sources
    assert "pto-2026.md" in sources


def test_fusion_rewards_documents_ranked_high_by_both_lists():
    fused = reciprocal_rank_fusion([["current", "old"], ["current", "other"]])
    assert fused[0][0] == "current"
    assert fused[0][1] > fused[1][1]


def test_quote_must_be_verbatim():
    text = "Full-time employees receive 20 days of paid time off."
    assert quote_in_chunk("20 days of paid time off", text)
    assert quote_in_chunk("20   days\nof paid time off", text)
    assert not quote_in_chunk("21 days of paid time off", text)
    assert not quote_in_chunk("20", text)


def test_uncited_claim_is_refused():
    chunk = Chunk(
        chunk_id="pto-2026-1",
        source="pto-2026.md",
        title="Allowance",
        text="Full-time employees receive 20 days of paid time off per calendar year.",
    )
    hit = Hit(chunk=chunk, score=0.03, bm25_rank=1, vector_rank=1)
    draft = DraftAnswer(
        refused=False,
        answer="Employees get 20 days.",
        citations=[CitationDraft(chunk_id="pto-2026-1", quote="employees get fifteen days off")],
    )
    verified = verify(draft, [hit])
    assert verified.refused
    assert verified.citations == []
    assert verified.dropped == 1


def test_verbatim_citation_is_kept():
    chunk = Chunk(
        chunk_id="pto-2026-1",
        source="pto-2026.md",
        title="Allowance",
        text="Full-time employees receive 20 days of paid time off per calendar year.",
    )
    hit = Hit(chunk=chunk, score=0.03, bm25_rank=1, vector_rank=1)
    draft = DraftAnswer(
        refused=False,
        answer="The current allowance is 20 days.",
        citations=[
            CitationDraft(
                chunk_id="pto-2026-1",
                quote="receive 20 days of paid time off",
            )
        ],
    )
    verified = verify(draft, [hit])
    assert not verified.refused
    assert verified.citations[0].source == "pto-2026.md"


def test_current_question_cannot_stand_on_a_superseded_policy():
    chunk = Chunk(
        chunk_id="pto-2024-1",
        source="pto-2024.md",
        title="Allowance",
        text="Full-time employees accrued 15 days of paid time off per calendar year under this 2024 policy.",
        topic="pto",
        status="superseded",
    )
    hit = Hit(chunk=chunk, score=0.02, bm25_rank=1, vector_rank=1)
    draft = DraftAnswer(
        refused=False,
        answer="Employees get 15 days.",
        citations=[CitationDraft(chunk_id="pto-2024-1", quote="accrued 15 days of paid time off")],
    )
    verified = verify(draft, [hit], "How many PTO days does the current policy give?")
    assert verified.refused
    assert verified.citations == []


def test_a_2024_question_may_cite_the_superseded_policy():
    chunk = Chunk(
        chunk_id="pto-2024-1",
        source="pto-2024.md",
        title="Allowance",
        text="Full-time employees accrued 15 days of paid time off per calendar year under this 2024 policy.",
        topic="pto",
        status="superseded",
    )
    hit = Hit(chunk=chunk, score=0.02, bm25_rank=1, vector_rank=1)
    draft = DraftAnswer(
        refused=False,
        answer="The 2024 policy accrued 15 days.",
        citations=[CitationDraft(chunk_id="pto-2024-1", quote="accrued 15 days of paid time off")],
    )
    verified = verify(draft, [hit], "How many PTO days did the 2024 policy accrue?")
    assert not verified.refused
    assert verified.citations[0].source == "pto-2024.md"


def test_search_prefers_the_vector_neighbor_when_words_also_match():
    chunks = [
        Chunk("old", "pto-2024.md", "2024", "superseded policy accrued 15 days in 2024"),
        Chunk("new", "pto-2026.md", "2026", "current policy employees receive 20 days in 2026"),
    ]
    index = Index(chunks, [[1.0, 0.0], [0.0, 1.0]])
    hits = index.search("current policy 2026 days", [0.0, 1.0], k=2)
    assert hits[0].chunk.chunk_id == "new"


def test_find_quote_span_returns_exact_offsets_with_normalized_whitespace():
    from app.grounding import find_quote_span

    raw_text = "Full-time employees receive   20\n\ndays of paid time off per calendar year."
    # Quote with standard single whitespace
    span = find_quote_span("receive 20 days of paid time off", raw_text)
    assert span is not None
    start, end = span
    assert raw_text[start:end] == "receive   20\n\ndays of paid time off"

    # Quote with irregular whitespace matching standard text
    std_text = "Full-time employees receive 20 days of paid time off per calendar year."
    span2 = find_quote_span("receive   20\ndays\n  of paid time off", std_text)
    assert span2 is not None
    start2, end2 = span2
    assert std_text[start2:end2] == "receive 20 days of paid time off"


def test_verified_citation_includes_span_offsets():
    chunk = Chunk(
        chunk_id="pto-2026-1",
        source="pto-2026.md",
        title="Allowance",
        text="Full-time employees receive 20 days of paid time off per calendar year.",
    )
    hit = Hit(chunk=chunk, score=0.03, bm25_rank=1, vector_rank=1)
    draft = DraftAnswer(
        refused=False,
        answer="The current allowance is 20 days.",
        citations=[
            CitationDraft(
                chunk_id="pto-2026-1",
                quote="receive 20 days of paid time off",
            )
        ],
    )
    verified = verify(draft, [hit])
    assert not verified.refused
    cit = verified.citations[0]
    assert cit.start_char == 20
    assert cit.end_char == 52
    assert chunk.text[cit.start_char:cit.end_char] == "receive 20 days of paid time off"
