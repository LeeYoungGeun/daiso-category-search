"""
M1 Embedding Adapter
Supports Google Gemini embeddings (primary) with mock fallback for testing.
"""
from __future__ import annotations

import hashlib
import math
import os
from typing import List, Optional, Protocol


class EmbeddingAdapter(Protocol):
    """Protocol for embedding adapters."""
    dim: int

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...

    def embed_query(self, text: str) -> List[float]:
        ...


class GoogleEmbeddingAdapter:
    """Google Gemini embeddings via google-genai SDK.

    Uses task_type separation:
    - RETRIEVAL_DOCUMENT for indexing
    - RETRIEVAL_QUERY for search queries
    """

    dim: int = 0

    def __init__(
        self,
        *,
        model: str = "gemini-embedding-001",
        api_key: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ):
        self.model = model
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        if not self.api_key:
            raise RuntimeError(
                "Missing Google API key. Set GEMINI_API_KEY or GOOGLE_API_KEY."
            )
        self.output_dimensionality = output_dimensionality

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise RuntimeError(
                "google-genai package not installed. Run: pip install google-genai"
            ) from e

        self._types = types
        self._client = genai.Client(api_key=self.api_key)

    def _embed(self, texts: List[str], *, task_type: str) -> List[List[float]]:
        if not texts:
            return []

        cfg_kwargs = {"task_type": task_type}
        if self.output_dimensionality:
            cfg_kwargs["output_dimensionality"] = int(self.output_dimensionality)

        config = self._types.EmbedContentConfig(**cfg_kwargs)

        BATCH_SIZE = 100
        out: List[List[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            res = self._client.models.embed_content(
                model=self.model,
                contents=batch,
                config=config,
            )
            out.extend([e.values for e in res.embeddings])

        if len(out) != len(texts):
            raise RuntimeError(
                f"Embedding size mismatch: input={len(texts)} output={len(out)}"
            )

        if self.dim == 0 and out:
            self.dim = len(out[0])

        return out

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed documents for indexing."""
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query for search."""
        return self._embed([text], task_type="RETRIEVAL_QUERY")[0]


class MockHashEmbedding:
    """Deterministic mock embedding for testing without API calls.

    Uses SHA-256 hash to generate stable pseudo-random vectors.
    NOT suitable for semantic evaluation — only for pipeline wiring tests.
    """

    def __init__(self, dim: int = 768):
        self.dim = dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_embed(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> List[float]:
        h = hashlib.sha256((text or "").encode("utf-8")).digest()
        vec: List[float] = []
        i = 0
        while len(vec) < self.dim:
            b = h[i % len(h)]
            vec.append(b / 255.0)
            i += 1
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        vec = [x / norm for x in vec]
        return vec


def build_embedding_adapter(
    provider: str = "google",
    model: str = "gemini-embedding-001",
    api_key: Optional[str] = None,
    output_dimensionality: Optional[int] = None,
    dim: int = 768,
) -> EmbeddingAdapter:
    """Factory function to create embedding adapter."""
    provider = provider.lower()

    if provider == "mock":
        return MockHashEmbedding(dim=dim)  # type: ignore[return-value]

    if provider == "google":
        return GoogleEmbeddingAdapter(  # type: ignore[return-value]
            model=model,
            api_key=api_key,
            output_dimensionality=output_dimensionality,
        )

    raise ValueError(f"Unsupported embedding provider: {provider}")
