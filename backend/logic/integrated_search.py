"""
Integrated Search Pipeline
Combines NLU → Hybrid Search (BM25+Vector+RRF) → Ambiguity Detection → Rerank → Location

M1 Update: Replaced SQLite LIKE search with Hybrid Search (Elasticsearch + Qdrant).
M2 Update: Added ambiguity detection, follow-up questions, 2-strike fallback, enhanced reranking.

Falls back to SQLite LIKE if external services are unavailable.
"""

import os
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

# Ensure project root is in path for absolute imports
import sys
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from poc.kms.nlu import analyze_text, expand_search_keywords
from backend.logic.reranker import rerank_candidates
from backend.logic.ambiguity import (
    detect_ambiguity,
    calculate_category_spread,
    generate_clarification_options,
    build_clarification_question,
    should_fallback,
)
from backend.database.database import search_products
from backend.database.category_matcher import match_product_to_category

logger = logging.getLogger(__name__)


def _try_init_hybrid_search():
    """Try to initialize hybrid search service. Returns None if unavailable."""
    try:
        from backend.search.config import HybridSearchConfig
        from backend.search.hybrid import HybridSearchService

        config = HybridSearchConfig.from_env()

        # Only init if URLs are configured
        if not config.elastic.url or not config.qdrant.url:
            logger.info("Hybrid search not configured (missing ELASTIC_URL or QDRANT_URL)")
            return None

        service = HybridSearchService(config)
        health = service.health_check()

        if health.get("elasticsearch") and health.get("qdrant"):
            logger.info("✅ Hybrid search service initialized (Elasticsearch + Qdrant)")
            return service
        else:
            logger.warning(f"⚠️ Hybrid search services not fully healthy: {health}")
            return None
    except Exception as e:
        logger.warning(f"⚠️ Hybrid search init failed, falling back to SQLite: {e}")
        return None


class IntegratedSearchPipeline:
    """
    Integrated pipeline for product search
    Pipeline: NLU → Keyword Expansion → Hybrid Search → Ambiguity Check → Rerank → Location

    M1: Uses Elasticsearch (BM25) + Qdrant (Vector) + RRF Fusion
    M2: Ambiguity detection, follow-up questions, 2-strike fallback
    Fallback: SQLite LIKE search if external services unavailable
    """

    def __init__(self):
        self.timing = {}
        self._hybrid_service = _try_init_hybrid_search()
        self._use_hybrid = self._hybrid_service is not None

    @property
    def search_mode(self) -> str:
        """Current search mode."""
        return "hybrid" if self._use_hybrid else "sqlite_fallback"

    async def search(
        self,
        query: str,
        store_id: str = "store_001",
        session_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        clarification_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Execute full search pipeline with M2 ambiguity handling.

        Args:
            query: User query text
            store_id: Store identifier
            session_id: Session identifier for context
            history: Conversation history
            clarification_count: Number of previous clarification attempts (for 2-strike fallback)

        Returns:
            Dict with search results, clarification info, and metadata
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()

        if history is None:
            history = []

        result = {
            "request_id": request_id,
            "query": query,
            "store_id": store_id,
            "session_id": session_id or request_id,
            "is_in_scope": True,
            "intent": None,
            "top3": [],
            "top1_handover": None,
            # M2: Clarification fields
            "needs_clarification": False,
            "clarification_question": None,
            "clarification_options": [],
            "clarification_count": clarification_count,
            "is_fallback": False,
            "timing_ms": {},
            "metadata": {"search_mode": self.search_mode},
        }

        try:
            # Step 1: NLU - Intent Analysis & Keyword Extraction
            nlu_start = time.time()
            nlu_result = await analyze_text(query, history=history)
            nlu_time = int((time.time() - nlu_start) * 1000)

            result["intent"] = nlu_result.intent.value
            result["metadata"]["nlu"] = {
                "slots": nlu_result.slots.model_dump(),
                "needs_clarification": nlu_result.needs_clarification,
                "token_usage": nlu_result.token_usage,
            }

            # Check if out of scope
            if nlu_result.intent.value == "UNSUPPORTED":
                result["is_in_scope"] = False
                result["message"] = "죄송합니다. 상품 찾기 외의 질문은 아직 답변하기 어렵습니다."
                result["timing_ms"] = {
                    "nlu": nlu_time,
                    "total": int((time.time() - start_time) * 1000),
                }
                return result

            if nlu_result.intent.value == "OTHER_INQUIRY":
                result["is_in_scope"] = False
                result["message"] = "일반 문의는 매장 직원에게 문의해 주세요."
                result["timing_ms"] = {
                    "nlu": nlu_time,
                    "total": int((time.time() - start_time) * 1000),
                }
                return result

            # Step 2: Keyword Expansion
            expand_start = time.time()
            search_keywords = []

            # Primary keyword from NLU
            primary_keyword = nlu_result.slots.item or nlu_result.slots.query_rewrite or query
            search_keywords.append(primary_keyword)

            # Expand keywords using Gemini
            expanded_keywords, expand_usage = await expand_search_keywords(
                primary_keyword,
                return_usage=True,
            )
            search_keywords.extend(expanded_keywords[:3])  # Top 3 expansions

            # Remove duplicates while preserving order
            search_keywords = list(dict.fromkeys(search_keywords))

            expand_time = int((time.time() - expand_start) * 1000)

            result["metadata"]["keywords"] = {
                "primary": primary_keyword,
                "expanded": search_keywords,
                "token_usage": expand_usage,
            }

            # Step 3: Search — Hybrid (M1) or SQLite fallback
            search_start = time.time()

            if self._use_hybrid:
                candidates = self._hybrid_search(search_keywords, result)
            else:
                candidates = self._sqlite_search(search_keywords)

            search_time = int((time.time() - search_start) * 1000)

            result["metadata"]["search"] = {
                **result["metadata"].get("search", {}),
                "candidates_count": len(candidates),
                "keywords_used": search_keywords,
                "mode": self.search_mode,
            }

            # Step 4: M2 — Ambiguity Detection
            ambiguity_start = time.time()

            category_spread = calculate_category_spread(candidates)
            ambiguity_result = detect_ambiguity(
                item=nlu_result.slots.item,
                attrs=nlu_result.slots.attrs,
                candidates_count=len(candidates),
                category_spread=category_spread,
                nlu_needs_clarification=nlu_result.needs_clarification,
            )

            ambiguity_time = int((time.time() - ambiguity_start) * 1000)

            result["metadata"]["ambiguity"] = {
                "type": ambiguity_result.ambiguity_type.value,
                "is_ambiguous": ambiguity_result.is_ambiguous,
                "confidence": ambiguity_result.confidence,
                "reason": ambiguity_result.reason,
                "category_spread": category_spread,
            }

            # Step 4b: M2 — Handle ambiguity (clarification or fallback)
            if ambiguity_result.is_ambiguous:
                if should_fallback(clarification_count):
                    # 2-strike fallback: stop asking, show best-effort results
                    logger.info(f"[M2] 2-strike fallback triggered (count={clarification_count})")
                    result["is_fallback"] = True
                    result["message"] = "정확한 상품을 찾기 어려워 가장 관련 있는 상품을 안내해 드립니다."
                    # Continue to reranking with what we have
                else:
                    # Generate clarification question
                    options = generate_clarification_options(candidates, item=nlu_result.slots.item)
                    question = build_clarification_question(nlu_result.slots.item, options)

                    result["needs_clarification"] = True
                    result["clarification_question"] = question
                    result["clarification_options"] = options
                    result["clarification_count"] = clarification_count + 1

                    # Still include partial results for context
                    if candidates:
                        result["top3"] = self._format_top3(candidates[:3])

                    result["timing_ms"] = {
                        "nlu": nlu_time,
                        "expand": expand_time,
                        "search": search_time,
                        "ambiguity": ambiguity_time,
                        "total": int((time.time() - start_time) * 1000),
                    }
                    return result

            # If no candidates found (and not handled by ambiguity)
            if not candidates:
                result["message"] = f"'{query}' 관련 상품을 찾을 수 없습니다. 다른 키워드로 검색해 주세요."
                result["timing_ms"] = {
                    "nlu": nlu_time,
                    "expand": expand_time,
                    "search": search_time,
                    "ambiguity": ambiguity_time,
                    "total": int((time.time() - start_time) * 1000),
                }
                return result

            # Step 5: Reranking with M2 enhanced reranker
            rerank_start = time.time()

            # Prepare candidates for reranking
            rerank_candidates_list = []
            for c in candidates:
                rerank_candidates_list.append({
                    "id": str(c["id"]),
                    "name": c["name"],
                    "desc": c.get("searchable_desc", c.get("text", c["name"])),
                    "price": c.get("price", 0),
                })

            rerank_result = rerank_candidates(query, rerank_candidates_list)
            rerank_time = int((time.time() - rerank_start) * 1000)

            selected_id = rerank_result.get("selected_id")

            result["metadata"]["rerank"] = {
                "selected_id": selected_id,
                "reason": rerank_result.get("reason", ""),
                "confidence": rerank_result.get("confidence", 0.0),
                "latency": rerank_result.get("latency", 0),
            }

            # Step 6: Location Mapping & Format Results
            location_start = time.time()

            top3 = self._format_top3(candidates[:3], selected_id=selected_id)

            location_time = int((time.time() - location_start) * 1000)

            # Step 7: QR Handover (placeholder)
            top1_product = top3[0] if top3 else None
            if top1_product:
                result["top1_handover"] = {
                    "qr_payload": f"https://daiso.app/product/{top1_product['product_id']}",
                    "expires_in_sec": 120,
                    "product_id": top1_product["product_id"],
                    "product_name": top1_product["name"],
                }

            result["top3"] = top3
            if not result.get("message"):
                result["message"] = f"'{query}' 관련 상품 {len(top3)}개를 찾았습니다."

            # Timing summary
            total_time = int((time.time() - start_time) * 1000)
            result["timing_ms"] = {
                "nlu": nlu_time,
                "expand": expand_time,
                "search": search_time,
                "ambiguity": ambiguity_time,
                "rerank": rerank_time,
                "location": location_time,
                "total": total_time,
            }

            return result

        except Exception as e:
            # Error handling
            logger.error(f"Search pipeline error: {e}", exc_info=True)
            result["error"] = str(e)
            result["message"] = "검색 중 오류가 발생했습니다. 다시 시도해 주세요."
            result["timing_ms"] = {
                "total": int((time.time() - start_time) * 1000),
            }
            return result

    def _format_top3(
        self,
        candidates: List[Dict[str, Any]],
        selected_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Format top 3 results with category mapping and rerank ordering."""
        top3 = []
        top1_product = None

        for idx, c in enumerate(candidates[:3]):
            # Match category
            major, middle = match_product_to_category(c["name"])

            product_data = {
                "product_id": c["id"],
                "name": c["name"],
                "price": c.get("price", 0),
                "category_major": c.get("category", major),
                "category_middle": middle,
                "location_text": f"{c.get('category', major)} > {middle}",
                "image_url": c.get("image_url"),
                "rank": idx + 1,
                "is_top1": False,
            }

            # Mark top1 based on reranking
            if selected_id and str(c["id"]) == str(selected_id):
                product_data["is_top1"] = True
                product_data["rank"] = 1
                top1_product = product_data
                top3.insert(0, product_data)  # Put at front
            else:
                top3.append(product_data)

        # Ensure top3 has exactly 3 items (or less if not enough)
        top3 = top3[:3]

        # If no top1 selected by reranker, use first result
        if not top1_product and top3:
            top3[0]["is_top1"] = True

        return top3

    def _hybrid_search(self, keywords: List[str], result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """M1: Hybrid search using Elasticsearch + Qdrant + RRF Fusion."""
        # Join keywords for search query
        query_text = " ".join(keywords)

        search_result = self._hybrid_service.search(query_text, top_k=10, mode="hybrid")

        # Convert ScoredDoc to candidate dict format
        candidates = []
        for doc in search_result.docs:
            candidates.append({
                "id": doc.doc_id,
                "name": doc.title or doc.doc_id,
                "text": doc.text,
                "searchable_desc": doc.payload.get("bm25_text", doc.text),
                "category": doc.category,
                "price": doc.payload.get("price", 0),
                "score": doc.score,
                "source": doc.source,
            })

        # Store hybrid search timing in metadata
        result["metadata"]["search"] = {
            "hybrid_timing": search_result.timing_ms,
            "hybrid_metadata": search_result.metadata,
        }

        return candidates

    def _sqlite_search(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """Fallback: SQLite LIKE search (M0 behavior)."""
        candidates = []
        for keyword in keywords:
            found = search_products(keyword)
            candidates.extend(found)
            if len(candidates) >= 10:
                break

        # Remove duplicates by product id
        seen_ids = set()
        unique_candidates = []
        for c in candidates:
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                unique_candidates.append(c)

        return unique_candidates[:10]


# Singleton instance
_pipeline = None


def get_pipeline() -> IntegratedSearchPipeline:
    """Get or create pipeline instance"""
    global _pipeline
    if _pipeline is None:
        _pipeline = IntegratedSearchPipeline()
    return _pipeline
