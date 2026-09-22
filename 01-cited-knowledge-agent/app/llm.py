"""Gemini calls for this project. The key is read from .env and never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

STRONG_MODEL = "gemini-3.8-flash"
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIMS = 768


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0


def redact(message: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    cleaned = message.replace(key, "[redacted]") if key else message
    return " ".join(cleaned.split())[:800]


def get_client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Add it to this project's .env and restart."
        )
    return genai.Client(api_key=key)


def _usage(response: object) -> Usage:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return Usage()
    return Usage(
        prompt_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0),
    )


def _generate(client: genai.Client, *, model: str, system: str, prompt: str, schema: type[BaseModel] | None, max_output_tokens: int):
    last_message = "Gemini returned no response."
    for use_thinking in (True, False):
        config_kwargs: dict = {
            "system_instruction": system,
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if use_thinking:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            )
        if schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            last_message = redact(str(exc))
            if use_thinking and "thinking" in last_message.lower():
                continue
            raise RuntimeError(f"Gemini request failed for model {model}: {last_message}") from exc
    raise RuntimeError(f"Gemini request failed for model {model}: {last_message}")


def generate_model(
    client: genai.Client,
    *,
    model: str,
    system: str,
    prompt: str,
    schema: type[BaseModel],
    max_output_tokens: int = 2048,
) -> tuple[BaseModel, Usage]:
    response = _generate(
        client,
        model=model,
        system=system,
        prompt=prompt,
        schema=schema,
        max_output_tokens=max_output_tokens,
    )
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not raw:
        raise RuntimeError(f"Gemini returned an empty JSON response for model {model}.")
    try:
        parsed = schema.model_validate_json(raw)
    except Exception as exc:
        raise RuntimeError(
            f"Gemini JSON did not match {schema.__name__}: {redact(str(exc))}"
        ) from exc
    return parsed, _usage(response)


def embed_texts(client: genai.Client, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    try:
        response = client.models.embed_content(
            model=EMBED_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMS),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Gemini embeddings failed for model {EMBED_MODEL}: {redact(str(exc))}"
        ) from exc
    vectors = [[float(value) for value in item.values] for item in response.embeddings]
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"Embedding count mismatch: sent {len(texts)} texts, got {len(vectors)} vectors."
        )
    return vectors
