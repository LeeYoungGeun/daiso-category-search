from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import List, Optional, Protocol


class EmbeddingAdapter(Protocol):
    dim: int

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...


class GoogleEmbeddingAdapter:
    """Google Gemini embeddings via google-genai.

    - Auth: GOOGLE_API_KEY or GEMINI_API_KEY (or cfg['api_key']).
    - Default model: gemini-embedding-001.
    - Supports task_type separation: documents vs queries.
    """

    dim: int = 0  # may be unknown until first call

    def __init__(
        self,
        *,
        model: str = "gemini-embedding-001",
        api_key: Optional[str] = None,
        output_dimensionality: Optional[int] = None,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Missing Google API key. Set GOOGLE_API_KEY (or GEMINI_API_KEY) in .env / environment."
            )
        self.output_dimensionality = output_dimensionality

        try:
            from google import genai
            from google.genai import types
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "google-genai python package is not installed. Install google-genai to use provider=google."
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

        # Google BatchEmbedContentsRequest 제한: 한 배치에 최대 100개
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

        # 방어: 입력/출력 개수 불일치 시 즉시 실패시켜 디버깅 용이하게
        if len(out) != len(texts):
            raise RuntimeError(f"Google embeddings size mismatch: in={len(texts)} out={len(out)}")

        # dim 자동 세팅
        if self.dim == 0 and out:
            self.dim = len(out[0])

        return out

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text], task_type="RETRIEVAL_QUERY")[0]

    # Back-compat with EmbeddingAdapter Protocol
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        # Treat as documents by default.
        return self.embed_documents(texts)


@dataclass
class MockHashEmbedding:
    """Deterministic local embedding.

    - No external API.
    - Suitable for pipeline wiring and regression harness.
    - Not suitable for semantic quality evaluation.
    """

    dim: int = 128

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for t in texts:
            # Stable hash -> pseudo-random bytes
            h = hashlib.sha256((t or "").encode("utf-8")).digest()
            # Expand to dim
            vec: List[float] = []
            i = 0
            while len(vec) < self.dim:
                b = h[i % len(h)]
                vec.append(b / 255.0)
                i += 1
            # L2 normalize
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vec = [x / norm for x in vec]
            out.append(vec)
        return out


def build_embedding_adapter(cfg: dict) -> EmbeddingAdapter:
    provider = (cfg.get("provider") or "mock").lower()
    if provider == "mock":
        dim = int(cfg.get("dim") or 128)
        return MockHashEmbedding(dim=dim)

    if provider == "openai":
        # Optional dependency: openai
        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError("openai python package is not installed. Use provider=mock or install openai.") from e

        model = cfg.get("model") or "text-embedding-3-small"
        client = OpenAI()

        class _OpenAIEmbedding:
            dim = 0

            def embed_texts(self, texts: List[str]) -> List[List[float]]:
                res = client.embeddings.create(model=model, input=texts)
                return [d.embedding for d in res.data]

        return _OpenAIEmbedding()

    if provider == "google":
        model = cfg.get("model") or "gemini-embedding-001"
        api_key = cfg.get("api_key")
        output_dimensionality = cfg.get("output_dimensionality")
        return GoogleEmbeddingAdapter(
            model=model,
            api_key=api_key,
            output_dimensionality=output_dimensionality,
        )

    raise ValueError(f"Unsupported embedding provider: {provider}")
