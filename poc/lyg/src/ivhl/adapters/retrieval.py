from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import requests

from ivhl.core.types import Document, ScoredDoc


class VectorRetriever(Protocol):
    def query(self, qvec: List[float], *, top_k: int) -> List[ScoredDoc]:
        ...


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    denom = na * nb
    if denom == 0.0:
        return 0.0
    return float(s / denom)


@dataclass
class BruteForceVectorRetriever:
    """
    Local dense retriever for debugging / baseline.
    Uses doc_id as key.
    """
    docs: List[Document]
    doc_vecs: Dict[str, List[float]]

    def query(self, qvec: List[float], *, top_k: int) -> List[ScoredDoc]:
        scored: List[ScoredDoc] = []
        for d in self.docs:
            v = self.doc_vecs.get(d.doc_id)
            if v is None:
                continue
            score = _cosine(qvec, v)
            scored.append(ScoredDoc(doc_id=d.doc_id, score=score, source="dense"))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[: int(top_k)]


@dataclass
class QdrantVectorRetriever:
    """
    Qdrant dense retriever.

    IMPORTANT:
    - Our Qdrant point.id is UUID/uint (NOT the original doc_id string).
    - The original doc_id is stored in payload["doc_id"].
    - Therefore we must return payload["doc_id"] for fair evaluation + fusion.
    """
    url: str
    collection: str
    api_key: str = ""
    timeout_s: int = 30
    max_retry: int = 5
    retry_sleep_base: float = 1.5

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            # Qdrant supports 'api-key' header
            h["api-key"] = self.api_key
        return h

    def query(self, qvec: List[float], *, top_k: int) -> List[ScoredDoc]:
        if not qvec:
            return []

        endpoint = f"{self.url.rstrip('/')}/collections/{self.collection}/points/search"
        body: Dict[str, Any] = {
            "vector": qvec,
            "limit": int(top_k),
            "with_payload": True,   # ✅ payload.doc_id로 복원
            "with_vector": False,
        }

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retry + 1):
            try:
                r = requests.post(endpoint, headers=self._headers(), json=body, timeout=self.timeout_s)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(self.retry_sleep_base * attempt)
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f"Qdrant search failed: {r.status_code} {r.text}")

                data = r.json()
                result = data.get("result") or []

                out: List[ScoredDoc] = []
                for item in result:
                    payload = item.get("payload") or {}
                    doc_id = (payload.get("doc_id") or "").strip()  # ✅ 원본 doc_id
                    score = float(item.get("score") or 0.0)

                    # fallback: payload에 없으면 qdrant id라도 반환
                    if not doc_id:
                        pid = item.get("id")
                        if pid is None:
                            continue
                        doc_id = str(pid)

                    out.append(ScoredDoc(doc_id=doc_id, score=score, source="dense"))

                return out

            except Exception as e:
                last_exc = e
                time.sleep(self.retry_sleep_base * attempt)

        raise RuntimeError(f"Qdrant search failed after retries: {last_exc}")
