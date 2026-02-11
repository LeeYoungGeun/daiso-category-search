"""
M1 Hybrid Search Service
BM25 (Elasticsearch) + Vector (Qdrant) + RRF/Weighted Fusion

Usage:
    from backend.search.hybrid import HybridSearchService
    from backend.search.config import HybridSearchConfig

    cfg = HybridSearchConfig.from_env()
    svc = HybridSearchService(cfg)
    results = svc.search("욕실 매트", top_k=10)
"""
from __future__ import annotations

import re
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from backend.search.config import HybridSearchConfig
from backend.search.embedding import build_embedding_adapter, EmbeddingAdapter

logger = logging.getLogger(__name__)


# ─── Data Types ──────────────────────────────────────────────────────────────

@dataclass
class ScoredDoc:
    """A document with a relevance score."""
    doc_id: str
    score: float
    source: str = ""          # "bm25", "dense", "fused"
    title: str = ""
    text: str = ""
    category: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Result of a hybrid search."""
    query: str
    docs: List[ScoredDoc]
    timing_ms: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─── Elasticsearch BM25 Client ───────────────────────────────────────────────

class ElasticBM25Client:
    """Elasticsearch BM25 retriever."""

    def __init__(self, url: str, index: str, api_key: str = "", auth_header: str = "", timeout_s: int = 30):
        self.url = url.rstrip("/")
        self.index = index
        self.api_key = api_key
        self.auth_header = auth_header
        self.timeout_s = timeout_s

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        ah = (self.auth_header or "").strip()
        if ah:
            h["Authorization"] = ah
            return h
        if self.api_key:
            key = self.api_key.strip()
            if key.lower().startswith(("apikey ", "bearer ", "basic ")):
                h["Authorization"] = key
            else:
                h["Authorization"] = f"ApiKey {key}"
        return h

    def health_check(self) -> bool:
        """Check if Elasticsearch is reachable."""
        try:
            r = requests.get(f"{self.url}/_cluster/health", headers=self._headers(), timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def search(self, query_text: str, *, top_k: int = 30) -> List[ScoredDoc]:
        """BM25 search on bm25_text field."""
        qt = (query_text or "").strip()
        if not qt:
            return []

        url = f"{self.url}/{self.index}/_search"
        body: Dict[str, Any] = {
            "size": int(top_k),
            "track_total_hits": False,
            "query": {
                "match": {
                    "bm25_text": {
                        "query": qt,
                    }
                }
            },
        }

        try:
            r = requests.post(url, headers=self._headers(), json=body, timeout=self.timeout_s)
            if r.status_code != 200:
                logger.error(f"Elastic search failed: {r.status_code} {r.text[:200]}")
                return []

            data = r.json()
            hits = ((data.get("hits") or {}).get("hits")) or []
            out: List[ScoredDoc] = []
            for h in hits:
                doc_id = str(h.get("_id") or "")
                score = float(h.get("_score") or 0.0)
                source_data = h.get("_source") or {}
                if not doc_id:
                    continue
                out.append(ScoredDoc(
                    doc_id=doc_id,
                    score=score,
                    source="bm25",
                    title=source_data.get("title", ""),
                    text=source_data.get("text", ""),
                    category=source_data.get("category", ""),
                    payload=source_data,
                ))
            return out
        except Exception as e:
            logger.error(f"Elastic search error: {e}")
            return []


# ─── Qdrant Vector Client ────────────────────────────────────────────────────

class QdrantVectorClient:
    """Qdrant dense vector retriever."""

    def __init__(self, url: str, collection: str, api_key: str = "", timeout_s: int = 30):
        self.url = url.rstrip("/")
        self.collection = collection
        self.api_key = api_key
        self.timeout_s = timeout_s

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["api-key"] = self.api_key
        return h

    def health_check(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            r = requests.get(f"{self.url}/healthz", headers=self._headers(), timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def search(self, query_vector: List[float], *, top_k: int = 30) -> List[ScoredDoc]:
        """Vector similarity search."""
        if not query_vector:
            return []

        endpoint = f"{self.url}/collections/{self.collection}/points/search"
        body: Dict[str, Any] = {
            "vector": query_vector,
            "limit": int(top_k),
            "with_payload": True,
            "with_vector": False,
        }

        try:
            r = requests.post(endpoint, headers=self._headers(), json=body, timeout=self.timeout_s)
            if r.status_code != 200:
                logger.error(f"Qdrant search failed: {r.status_code} {r.text[:200]}")
                return []

            data = r.json()
            result = data.get("result") or []
            out: List[ScoredDoc] = []
            for item in result:
                payload = item.get("payload") or {}
                doc_id = (payload.get("doc_id") or "").strip()
                score = float(item.get("score") or 0.0)

                if not doc_id:
                    pid = item.get("id")
                    if pid is None:
                        continue
                    doc_id = str(pid)

                out.append(ScoredDoc(
                    doc_id=doc_id,
                    score=score,
                    source="dense",
                    title=payload.get("title", ""),
                    text=payload.get("text", ""),
                    category=payload.get("category", ""),
                    payload=payload,
                ))
            return out
        except Exception as e:
            logger.error(f"Qdrant search error: {e}")
            return []


# ─── Fusion Functions ─────────────────────────────────────────────────────────

def rrf_fusion(
    dense: List[ScoredDoc],
    sparse: List[ScoredDoc],
    *,
    rrf_k: int = 60,
    top_k: int = 10,
) -> List[ScoredDoc]:
    """Reciprocal Rank Fusion.

    score(doc) = sum(1 / (rrf_k + rank))
    """
    scores: Dict[str, float] = {}
    doc_map: Dict[str, ScoredDoc] = {}

    for lst in (dense, sparse):
        for rank, sd in enumerate(lst, start=1):
            scores[sd.doc_id] = scores.get(sd.doc_id, 0.0) + 1.0 / (rrf_k + rank)
            if sd.doc_id not in doc_map:
                doc_map[sd.doc_id] = sd

    merged = []
    for doc_id, score in scores.items():
        base = doc_map[doc_id]
        merged.append(ScoredDoc(
            doc_id=doc_id,
            score=score,
            source="fused",
            title=base.title,
            text=base.text,
            category=base.category,
            payload=base.payload,
        ))
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[:top_k]


def weighted_fusion(
    dense: List[ScoredDoc],
    sparse: List[ScoredDoc],
    *,
    alpha: float = 0.5,
    top_k: int = 10,
) -> List[ScoredDoc]:
    """Weighted sum after per-list min-max normalization."""
    doc_map: Dict[str, ScoredDoc] = {}

    def norm(lst: List[ScoredDoc]) -> Dict[str, float]:
        if not lst:
            return {}
        mx = max(x.score for x in lst)
        mn = min(x.score for x in lst)
        if mx <= mn:
            return {x.doc_id: 0.0 for x in lst}
        return {x.doc_id: (x.score - mn) / (mx - mn) for x in lst}

    nd = norm(dense)
    ns = norm(sparse)

    for sd in dense + sparse:
        if sd.doc_id not in doc_map:
            doc_map[sd.doc_id] = sd

    keys = set(nd.keys()) | set(ns.keys())
    scores: Dict[str, float] = {}
    for k in keys:
        scores[k] = alpha * nd.get(k, 0.0) + (1 - alpha) * ns.get(k, 0.0)

    merged = []
    for doc_id, score in scores.items():
        base = doc_map[doc_id]
        merged.append(ScoredDoc(
            doc_id=doc_id,
            score=score,
            source="fused",
            title=base.title,
            text=base.text,
            category=base.category,
            payload=base.payload,
        ))
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[:top_k]


# ─── Hybrid Search Service ───────────────────────────────────────────────────

class HybridSearchService:
    """Main hybrid search service combining BM25 + Vector + Fusion."""

    def __init__(self, config: Optional[HybridSearchConfig] = None):
        self.config = config or HybridSearchConfig.from_env()

        # Initialize clients
        self.elastic = ElasticBM25Client(
            url=self.config.elastic.url,
            index=self.config.elastic.index,
            api_key=self.config.elastic.api_key,
            auth_header=self.config.elastic.auth_header,
            timeout_s=self.config.elastic.timeout_s,
        )
        self.qdrant = QdrantVectorClient(
            url=self.config.qdrant.url,
            collection=self.config.qdrant.collection,
            api_key=self.config.qdrant.api_key,
            timeout_s=self.config.qdrant.timeout_s,
        )

        # Initialize embedding adapter
        self.embedder: EmbeddingAdapter = build_embedding_adapter(
            provider=self.config.embedding.provider,
            model=self.config.embedding.model,
            api_key=self.config.embedding.api_key,
            output_dimensionality=self.config.embedding.output_dimensionality,
        )

        logger.info(
            f"HybridSearchService initialized: "
            f"elastic={self.config.elastic.url}/{self.config.elastic.index}, "
            f"qdrant={self.config.qdrant.url}/{self.config.qdrant.collection}, "
            f"embedding={self.config.embedding.provider}/{self.config.embedding.model}"
        )

    def health_check(self) -> Dict[str, bool]:
        """Check health of all external services."""
        return {
            "elasticsearch": self.elastic.health_check(),
            "qdrant": self.qdrant.health_check(),
        }

    def search(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        mode: str = "hybrid",
    ) -> SearchResult:
        """Execute hybrid search.

        Args:
            query: Search query text
            top_k: Number of results to return (default: config.top_k_fused)
            mode: "hybrid" (default), "bm25_only", "dense_only"

        Returns:
            SearchResult with fused documents and timing info
        """
        top_k = top_k or self.config.top_k_fused
        timing: Dict[str, int] = {}
        metadata: Dict[str, Any] = {"mode": mode, "query": query}

        bm25_results: List[ScoredDoc] = []
        dense_results: List[ScoredDoc] = []

        # ── BM25 Search ──
        if mode in ("hybrid", "bm25_only"):
            t0 = time.time()
            bm25_results = self.elastic.search(
                query, top_k=self.config.top_k_bm25
            )
            timing["bm25_ms"] = int((time.time() - t0) * 1000)
            metadata["bm25_count"] = len(bm25_results)

        # ── Dense (Vector) Search ──
        if mode in ("hybrid", "dense_only"):
            t0 = time.time()
            query_vec = self.embedder.embed_query(query)
            timing["embed_ms"] = int((time.time() - t0) * 1000)

            t0 = time.time()
            dense_results = self.qdrant.search(
                query_vec, top_k=self.config.top_k_dense
            )
            timing["dense_ms"] = int((time.time() - t0) * 1000)
            metadata["dense_count"] = len(dense_results)

        # ── Fusion ──
        if mode == "hybrid" and bm25_results and dense_results:
            t0 = time.time()
            if self.config.fusion_method == "weighted":
                fused = weighted_fusion(
                    dense_results,
                    bm25_results,
                    alpha=self.config.fusion_alpha,
                    top_k=top_k,
                )
            else:
                fused = rrf_fusion(
                    dense_results,
                    bm25_results,
                    rrf_k=self.config.rrf_k,
                    top_k=top_k,
                )
            timing["fusion_ms"] = int((time.time() - t0) * 1000)
            docs = fused
        elif mode == "bm25_only":
            docs = bm25_results[:top_k]
        elif mode == "dense_only":
            docs = dense_results[:top_k]
        else:
            # Fallback: use whichever has results
            docs = (bm25_results or dense_results)[:top_k]

        timing["total_ms"] = sum(timing.values())
        metadata["result_count"] = len(docs)

        return SearchResult(
            query=query,
            docs=docs,
            timing_ms=timing,
            metadata=metadata,
        )

    def search_bm25_only(self, query: str, *, top_k: int = 10) -> SearchResult:
        """Convenience: BM25-only search."""
        return self.search(query, top_k=top_k, mode="bm25_only")

    def search_dense_only(self, query: str, *, top_k: int = 10) -> SearchResult:
        """Convenience: Dense-only search."""
        return self.search(query, top_k=top_k, mode="dense_only")
