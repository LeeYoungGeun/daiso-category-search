# src/ivhl/adapters/bm25.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import os
import time
import requests

from ivhl.core.types import Document, ScoredDoc


def _simple_tokenize(text: str) -> List[str]:
    return [t for t in (text or "").strip().split() if t]


@dataclass
class LocalBM25:
    docs: List[Document]

    def __post_init__(self) -> None:
        self._doc_texts: List[str] = [(d.title + " " + d.text).strip() for d in self.docs]
        self._doc_tokens: List[List[str]] = [_simple_tokenize(t) for t in self._doc_texts]

        self._df: Dict[str, int] = {}
        for toks in self._doc_tokens:
            for tok in set(toks):
                self._df[tok] = self._df.get(tok, 0) + 1

        self._N = max(len(self.docs), 1)
        self._avgdl = sum(len(t) for t in self._doc_tokens) / self._N

        self._k1 = 1.5
        self._b = 0.75

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return max(0.0, ((self._N - df + 0.5) / (df + 0.5)))

    def query(self, query_text: str, *, top_k: int = 50) -> List[ScoredDoc]:
        q_tokens = _simple_tokenize(query_text)
        if not q_tokens:
            return [
                ScoredDoc(doc_id=self.docs[i].doc_id, score=0.0, extra={"rank": i + 1})
                for i in range(min(top_k, len(self.docs)))
            ]

        scores: List[float] = [0.0 for _ in self.docs]
        for i, doc_toks in enumerate(self._doc_tokens):
            dl = len(doc_toks) or 1
            tf: Dict[str, int] = {}
            for t in doc_toks:
                tf[t] = tf.get(t, 0) + 1

            s = 0.0
            for term in q_tokens:
                f = tf.get(term, 0)
                if f <= 0:
                    continue
                idf = self._idf(term)
                denom = f + self._k1 * (1 - self._b + self._b * (dl / self._avgdl))
                s += idf * (f * (self._k1 + 1)) / max(denom, 1e-9)
            scores[i] = s

        idx_sorted = sorted(range(len(self.docs)), key=lambda i: scores[i], reverse=True)
        idx_sorted = idx_sorted[: min(top_k, len(idx_sorted))]

        out: List[ScoredDoc] = []
        for rank, i in enumerate(idx_sorted, start=1):
            out.append(ScoredDoc(doc_id=self.docs[i].doc_id, score=float(scores[i]), extra={"rank": rank}))
        return out


@dataclass
class ElasticBM25Retriever:
    """ElasticSearch BM25 retriever (/_search).

    전제:
    - index에 'bm25_text' 필드가 있고, 그 필드로 검색한다.
    - 문서 _id == doc_id 로 색인되어 있어야 (doc_id 매핑이 일관).
    """
    docs: List[Document]
    base_url: str                 # ex) http://localhost:9200
    index: str                    # ex) products
    api_key: str = ""             # optional
    auth_header: str = ""         # optional: "ApiKey xxx" or "Bearer xxx" or "Basic xxx"
    timeout_s: int = 30
    max_retry: int = 5
    retry_sleep_base: float = 1.5

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        ah = (self.auth_header or "").strip() or os.environ.get("ELASTIC_AUTH_HEADER", "").strip()
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

    def query(self, query_text: str, *, top_k: int = 50) -> List[ScoredDoc]:
        qt = (query_text or "").strip()
        if not qt:
            # 비교 실험용: 빈 쿼리면 0점으로라도 top_k 반환(로컬과 동일한 “항상 top_k” 규약)
            return [
                ScoredDoc(doc_id=self.docs[i].doc_id, score=0.0, extra={"rank": i + 1})
                for i in range(min(top_k, len(self.docs)))
            ]

        url = f"{self.base_url.rstrip('/')}/{self.index}/_search"
        body: Dict[str, Any] = {
            "size": int(top_k),
            "track_total_hits": False,
            "query": {
                "match": {
                    "bm25_text": {
                        "query": qt
                    }
                }
            }
        }

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retry + 1):
            try:
                r = requests.post(url, headers=self._headers(), json=body, timeout=self.timeout_s)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(self.retry_sleep_base * attempt)
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f"Elastic _search failed: {r.status_code} {r.text}")

                data = r.json()
                hits = ((data.get("hits") or {}).get("hits")) or []
                out: List[ScoredDoc] = []
                for rank, h in enumerate(hits, start=1):
                    doc_id = str(h.get("_id") or "")
                    score = float(h.get("_score") or 0.0)
                    if not doc_id:
                        continue
                    out.append(ScoredDoc(doc_id=doc_id, score=score, extra={"rank": rank}, source="bm25"))
                return out
            except Exception as e:
                last_exc = e
                time.sleep(self.retry_sleep_base * attempt)

        raise RuntimeError(f"Elastic search failed after retries: {last_exc}")
