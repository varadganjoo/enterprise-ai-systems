"""Cache handbook embeddings so a restart does not re-embed unchanged chunks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from google import genai

from app.corpus import Chunk
from app.llm import EMBED_DIMS, EMBED_MODEL, embed_texts

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "cache" / "embeddings.json"


def _cache_key(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{EMBED_MODEL}:{EMBED_DIMS}:{digest}"


def load_vectors(client: genai.Client, chunks: list[Chunk], cache_path: Path = CACHE_PATH) -> list[list[float]]:
    cache: dict[str, list[float]] = {}
    if cache_path.exists():
        loaded = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            cache = {str(key): [float(value) for value in vector] for key, vector in loaded.items()}

    missing = [chunk for chunk in chunks if _cache_key(chunk.text) not in cache]
    if missing:
        vectors = embed_texts(client, [chunk.text for chunk in missing])
        for chunk, vector in zip(missing, vectors):
            if len(vector) != EMBED_DIMS:
                raise RuntimeError(
                    f"Embedding for {chunk.chunk_id} has {len(vector)} dimensions, expected {EMBED_DIMS}."
                )
            cache[_cache_key(chunk.text)] = vector
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

    return [cache[_cache_key(chunk.text)] for chunk in chunks]
