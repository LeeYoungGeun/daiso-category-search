"""
M1 Hybrid Search Configuration
Loads from environment variables with sensible defaults for local Docker.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ElasticConfig:
    url: str = ""
    index: str = "products"
    api_key: str = ""
    auth_header: str = ""
    timeout_s: int = 30

    @classmethod
    def from_env(cls) -> "ElasticConfig":
        return cls(
            url=os.getenv("ELASTIC_URL", "http://localhost:9200").rstrip("/"),
            index=os.getenv("ELASTIC_INDEX", "products"),
            api_key=os.getenv("ELASTIC_API_KEY", ""),
            auth_header=os.getenv("ELASTIC_AUTH_HEADER", ""),
            timeout_s=int(os.getenv("ELASTIC_TIMEOUT", "30")),
        )


@dataclass
class QdrantConfig:
    url: str = ""
    collection: str = "products"
    api_key: str = ""
    timeout_s: int = 30

    @classmethod
    def from_env(cls) -> "QdrantConfig":
        return cls(
            url=os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/"),
            collection=os.getenv("QDRANT_COLLECTION", "products"),
            api_key=os.getenv("QDRANT_API_KEY", ""),
            timeout_s=int(os.getenv("QDRANT_TIMEOUT", "30")),
        )


@dataclass
class RedisConfig:
    url: str = ""
    ttl_seconds: int = 300  # 5 min cache

    @classmethod
    def from_env(cls) -> "RedisConfig":
        return cls(
            url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            ttl_seconds=int(os.getenv("REDIS_CACHE_TTL", "300")),
        )


@dataclass
class EmbeddingConfig:
    provider: str = "google"
    model: str = "gemini-embedding-001"
    api_key: str = ""
    output_dimensionality: Optional[int] = None

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(
            provider=os.getenv("EMBEDDING_PROVIDER", "google"),
            model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"),
            api_key=os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
            output_dimensionality=int(d) if (d := os.getenv("EMBEDDING_DIM")) else None,
        )


@dataclass
class HybridSearchConfig:
    """Top-level config for the hybrid search pipeline."""
    elastic: ElasticConfig = field(default_factory=ElasticConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)

    # Fusion parameters
    top_k_bm25: int = 30
    top_k_dense: int = 30
    top_k_fused: int = 10
    rrf_k: int = 60
    fusion_method: str = "rrf"  # "rrf" or "weighted"
    fusion_alpha: float = 0.5   # only for weighted fusion

    @classmethod
    def from_env(cls) -> "HybridSearchConfig":
        return cls(
            elastic=ElasticConfig.from_env(),
            qdrant=QdrantConfig.from_env(),
            redis=RedisConfig.from_env(),
            embedding=EmbeddingConfig.from_env(),
            top_k_bm25=int(os.getenv("SEARCH_TOP_K_BM25", "30")),
            top_k_dense=int(os.getenv("SEARCH_TOP_K_DENSE", "30")),
            top_k_fused=int(os.getenv("SEARCH_TOP_K_FUSED", "10")),
            rrf_k=int(os.getenv("SEARCH_RRF_K", "60")),
            fusion_method=os.getenv("SEARCH_FUSION_METHOD", "rrf"),
            fusion_alpha=float(os.getenv("SEARCH_FUSION_ALPHA", "0.5")),
        )
