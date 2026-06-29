"""Doubao embedding service.

Calls the Ark-compatible /embeddings endpoint (same key + base URL as the LLM).
Vectors are L2-normalised so cosine similarity == dot product.

Query inputs get an instruction prefix for better retrieval quality.
Document inputs (curriculum KB) are encoded as-is.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from src.config import settings

logger = logging.getLogger(__name__)

_QUERY_PREFIX = (
    "Instruct: Given a physics question from a middle school student, "
    "retrieve relevant knowledge points that cover the concepts needed to answer it\nQuery: "
)


def _call_embeddings(texts: list[str]) -> list[list[float]]:
    """Raw HTTP call to /embeddings. Returns list of float vectors."""
    resp = requests.post(
        f"{settings.doubao_seed_base_url}/embeddings",
        json={
            "model": settings.doubao_embedding_model,
            "input": texts,
            "encoding_format": "float",
        },
        headers={
            "Authorization": f"Bearer {settings.doubao_seed_api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # Sort by index to preserve input order
    items = sorted(data["data"], key=lambda d: d["index"])
    vectors = [item["embedding"] for item in items]

    # MRL truncation to target dim, then L2 normalise
    dim = settings.embedding_dim
    result: list[list[float]] = []
    for vec in vectors:
        v = vec[:dim]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        result.append([x / norm for x in v])
    return result


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed curriculum knowledge point texts (no instruction prefix)."""
    if not texts:
        return []
    settings.validate_required_for_ai()
    return _call_embeddings(texts)


def embed_query(text: str) -> list[float]:
    """Embed a student question with retrieval instruction prefix."""
    settings.validate_required_for_ai()
    prefixed = _QUERY_PREFIX + text
    return _call_embeddings([prefixed])[0]


def batch_embed_documents(
    texts: list[str],
    batch_size: int = 32,
) -> list[list[float]]:
    """Embed in batches to stay within API limits."""
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        results.extend(embed_documents(chunk))
    return results
