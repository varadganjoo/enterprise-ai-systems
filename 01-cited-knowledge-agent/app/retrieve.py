"""Hybrid retrieval: BM25 plus embeddings, fused with reciprocal rank fusion."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.corpus import Chunk

TOKEN = re.compile(r"[a-z0-9$]+")
RRF_K = 60


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    bm25_rank: int
    vector_rank: int


def tokenize(text: str) -> list[str]:
    tokens = TOKEN.findall(text.lower())
    return tokens or ["empty"]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = left_norm = right_norm = 0.0
    for a_value, b_value in zip(left, right):
        dot += a_value * b_value
        left_norm += a_value * a_value
        right_norm += b_value * b_value
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _ranks(ids: list[str], scores: list[float]) -> list[str]:
    order = sorted(range(len(ids)), key=lambda index: (-scores[index], index))
    return [ids[index] for index in order]


class Index:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(
                f"Chunk count {len(chunks)} does not match vector count {len(vectors)}."
            )
        if not chunks:
            raise ValueError("Cannot build an index from zero chunks.")
        self.chunks = chunks
        self.vectors = vectors
        self._by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self._bm25 = BM25Okapi([tokenize(chunk.text) for chunk in chunks])

    def search(self, query: str, query_vector: list[float], k: int = 4) -> list[Hit]:
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}.")
        ids = [chunk.chunk_id for chunk in self.chunks]
        bm25_scores = [float(score) for score in self._bm25.get_scores(tokenize(query))]
        vector_scores = [cosine(query_vector, vector) for vector in self.vectors]
        bm25_order = _ranks(ids, bm25_scores)
        vector_order = _ranks(ids, vector_scores)
        fused = reciprocal_rank_fusion([bm25_order, vector_order])
        bm25_rank = {doc_id: rank + 1 for rank, doc_id in enumerate(bm25_order)}
        vector_rank = {doc_id: rank + 1 for rank, doc_id in enumerate(vector_order)}
        hits: list[Hit] = []
        for doc_id, score in fused[:k]:
            hits.append(
                Hit(
                    chunk=self._by_id[doc_id],
                    score=score,
                    bm25_rank=bm25_rank[doc_id],
                    vector_rank=vector_rank[doc_id],
                )
            )
        return hits
