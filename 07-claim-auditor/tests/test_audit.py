from pathlib import Path

from app.audit import Claim, Finding, adjudicate, load_sources

ROOT = Path(__file__).resolve().parents[1]


def test_a_current_quote_is_supported_and_a_stale_quote_is_contradicted():
    sources = load_sources(ROOT / "data" / "sources")
    findings = adjudicate(
        [
            Claim(
                text="The current policy gives 20 days.",
                quote="receive 20 days of paid time off",
                chunk_id="pto-2026",
            ),
            Claim(
                text="The current policy gives 15 days.",
                quote="accrued 15 days of paid time off",
                chunk_id="pto-2024",
            ),
            Claim(text="The office is in Paris.", quote="office is in Paris", chunk_id="pto-2026"),
        ],
        sources,
    )
    by_text = {finding.text: finding for finding in findings}
    assert by_text["The current policy gives 20 days."].verdict == "supported"
    assert by_text["The current policy gives 15 days."].verdict == "contradicted"
    assert by_text["The office is in Paris."].verdict == "unverifiable"
    assert all(isinstance(finding, Finding) for finding in findings)


def test_the_model_cannot_mark_a_missing_quote_supported():
    sources = load_sources(ROOT / "data" / "sources")
    findings = adjudicate(
        [Claim(text="Employees get 20 days.", quote="not in the file", chunk_id="pto-2026")],
        sources,
    )
    assert findings[0].verdict == "unverifiable"
    assert findings[0].confidence == 0.0


def test_superseded_claim_without_asserting_current_is_marked_superseded():
    from app.audit import Verdict

    sources = load_sources(ROOT / "data" / "sources")
    findings = adjudicate(
        [
            Claim(
                text="In 2024, employees accrued 15 days of PTO.",
                quote="accrued 15 days of paid time off",
                chunk_id="pto-2024",
            )
        ],
        sources,
    )
    finding = findings[0]
    assert finding.verdict == Verdict.SUPERSEDED
    assert finding.verdict == "SUPERSEDED"
    assert finding.verdict == "superseded"
    assert finding.confidence >= 0.90
    assert finding.start_char > 0
    assert finding.end_char > finding.start_char
    source_2024 = next(s for s in sources if s.chunk_id == "pto-2024")
    assert source_2024.text[finding.start_char:finding.end_char] == finding.quote


def test_supported_claim_has_exact_character_offsets_and_full_confidence():
    from app.audit import Verdict

    sources = load_sources(ROOT / "data" / "sources")
    findings = adjudicate(
        [
            Claim(
                text="The current policy gives 20 days.",
                quote="receive 20 days of paid time off",
                chunk_id="pto-2026",
            )
        ],
        sources,
    )
    finding = findings[0]
    assert finding.verdict == Verdict.SUPPORTED
    assert finding.confidence == 1.0
    source_2026 = next(s for s in sources if s.chunk_id == "pto-2026")
    assert source_2026.text[finding.start_char:finding.end_char] == finding.quote
