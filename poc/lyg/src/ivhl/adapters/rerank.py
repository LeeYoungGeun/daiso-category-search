from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol

from ivhl.core.tokenize import tokenize
from ivhl.core.types import Document, ScoredDoc


class Reranker(Protocol):
    def rerank(self, query_text: str, docs: List[Document], *, top_k: int) -> List[ScoredDoc]:
        ...


@dataclass
class MockOverlapReranker:
    """Local reranker using token overlap ratio.

    This is NOT semantic; it is a deterministic heuristic to validate pipeline wiring.
    """

    def rerank(self, query_text: str, docs: List[Document], *, top_k: int) -> List[ScoredDoc]:
        q = set(tokenize(query_text))
        scored: List[ScoredDoc] = []
        for d in docs:
            dt = set(tokenize((d.title or "") + " " + (d.text or "")))
            if not q or not dt:
                score = 0.0
            else:
                score = len(q & dt) / len(q)
            scored.append(ScoredDoc(doc_id=d.doc_id, score=score, source="rerank"))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]


def build_reranker(cfg: dict) -> Reranker:
    provider = (cfg.get("provider") or "mock").lower()
    if provider == "mock":
        return MockOverlapReranker()

    if provider == "cohere":
        # Optional dependency: cohere
        try:
            import cohere
        except Exception as e:  # pragma: no cover
            raise RuntimeError("cohere python package is not installed. Use provider=mock or install cohere.") from e

        model = cfg.get("model") or "rerank-v4.0-fast"
        client = cohere.Client()  # expects COHERE_API_KEY env

        class _CohereReranker:
            def rerank(self, query_text: str, docs: List[Document], *, top_k: int) -> List[ScoredDoc]:
                texts = [((d.title or "") + "\n" + (d.text or "")).strip() for d in docs]
                resp = client.rerank(model=model, query=query_text, documents=texts, top_n=min(top_k, len(texts)))
                # resp.results contains indexes and relevance_scores
                out: List[ScoredDoc] = []
                for r in resp.results:
                    doc = docs[r.index]
                    out.append(ScoredDoc(doc_id=doc.doc_id, score=float(r.relevance_score), source="rerank"))
                out.sort(key=lambda x: x.score, reverse=True)
                return out

        return _CohereReranker()

    raise ValueError(f"Unsupported rerank provider: {provider}")
