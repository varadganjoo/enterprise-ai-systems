"""Run the handbook golden set and print a scorecard. Requires GEMINI_API_KEY."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.corpus import load_chunks  # noqa: E402
from app.embeddings import load_vectors  # noqa: E402
from app.llm import STRONG_MODEL, embed_texts, get_client  # noqa: E402
from app.retrieve import Index  # noqa: E402
from app.service import answer_question, gemini_complete  # noqa: E402


def main() -> None:
    cases = json.loads((ROOT / "evals" / "golden.json").read_text(encoding="utf-8"))
    client = get_client()
    chunks = load_chunks(ROOT / "data" / "handbook")
    index = Index(chunks, load_vectors(client, chunks))
    retrieval_hits = 0
    answer_hits = 0
    refusal_hits = 0
    refusal_total = 0
    answered = 0
    faithful = 0
    prompt_tokens = 0
    output_tokens = 0
    latency_ms = 0

    for case in cases:
        started = time.perf_counter()
        vector = embed_texts(client, [case["question"]])[0]

        def complete(question, hits, case=case):
            return gemini_complete(client, STRONG_MODEL, question, hits)

        result = answer_question(index, case["question"], vector, complete)
        elapsed = int((time.perf_counter() - started) * 1000)
        latency_ms += elapsed
        prompt_tokens += result.prompt_tokens
        output_tokens += result.output_tokens
        retrieved = {hit.chunk.source for hit in result.hits}
        cited = {citation.source for citation in result.citations}
        source = case.get("source")
        retrieval_ok = source is None or source in retrieved
        if retrieval_ok and source is not None:
            retrieval_hits += 1
        if case["expect_refused"]:
            refusal_total += 1
            if result.refused:
                refusal_hits += 1
        else:
            answered += 1
            phrases = [phrase.lower() for phrase in case.get("answer_contains", [])]
            text = result.answer.lower()
            phrases_ok = all(phrase in text for phrase in phrases)
            citation_ok = source in cited and all(
                citation.quote.lower() in " ".join(
                    chunk.text.lower().split()
                    for chunk in chunks
                    if chunk.chunk_id == citation.chunk_id
                )
                for citation in result.citations
            )
            if not result.refused and phrases_ok and citation_ok:
                answer_hits += 1
                faithful += 1
        status = "ok" if (
            (case["expect_refused"] and result.refused)
            or (
                not case["expect_refused"]
                and not result.refused
                and (source in cited)
            )
        ) else "miss"
        print(
            f"{status:4} {case['id']:18} refused={result.refused!s:5} "
            f"retrieved={sorted(retrieved)} cited={sorted(cited)} {elapsed}ms"
        )

    retrieval_total = sum(1 for case in cases if case.get("source"))
    print("---")
    print(f"retrieval_hit_rate {retrieval_hits}/{retrieval_total}")
    print(f"grounded_answer_rate {answer_hits}/{answered}")
    print(f"verbatim_citation_rate {faithful}/{answered}")
    print(f"refusal_accuracy {refusal_hits}/{refusal_total}")
    count = len(cases)
    print(f"mean_latency_ms {latency_ms // count}")
    print(f"total_prompt_tokens {prompt_tokens}")
    print(f"total_output_tokens {output_tokens}")
    print(f"model {STRONG_MODEL}")


if __name__ == "__main__":
    main()
