"""
Integrated Search Pipeline (BM25-only safe by default)
- NLU (local / vendor-off)
- Keyword expansion:
    - SAFE_MODE=1 or VENDOR_ENABLED!=true => NO external calls (no Gemini)
- Search:
    - SEARCH_MODE=bm25_only => Elasticsearch BM25 only (NO Qdrant, NO embedding)
    - SEARCH_MODE=dense_only => Qdrant dense only (requires embedding)
    - SEARCH_MODE=hybrid => BM25 + Dense + Fusion (requires embedding)
    - If ES is unavailable => SQLite fallback
- Ambiguity:
    - Reduced false-positive in bm25_only when top3 are same major category
"""

import os
import time
import uuid
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from poc.kms.nlu import analyze_text, expand_search_keywords
from backend.logic.reranker import rerank_candidates
from backend.search.cache import cache_get, cache_set
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


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default


def _effective_search_mode() -> str:
    mode = _env_str("SEARCH_MODE", "hybrid").strip().lower()
    if mode in ("bm25_only", "dense_only", "hybrid", "auto"):
        return mode
    return "hybrid"


def _vendor_allowed() -> bool:
    if _env_bool("SAFE_MODE", False):
        return False
    return _env_bool("VENDOR_ENABLED", False)


def _try_init_hybrid_service():
    try:
        from backend.search.config import HybridSearchConfig
        from backend.search.hybrid import HybridSearchService

        cfg = HybridSearchConfig.from_env()

        if not getattr(cfg.elastic, "url", None):
            logger.warning("Hybrid search not configured: missing ELASTIC_URL")
            return None

        if not getattr(cfg.qdrant, "url", None):
            logger.warning("Hybrid search not configured: missing QDRANT_URL")
            return None

        svc = HybridSearchService(cfg)

        try:
            health = svc.health_check()
            logger.warning(f"[HYBRID health] raw={health}")
        except Exception as e:
            logger.warning(f"⚠️ HYBRID health_check failed: {e}")

        logger.info("✅ Hybrid search service initialized (BM25 + Dense available)")
        return svc

    except Exception as e:
        logger.warning(f"⚠️ Hybrid init failed (fallback to BM25/SQLite): {e}")
        return None


def _try_init_bm25_service():
    try:
        from backend.search.config import HybridSearchConfig
        from backend.search.hybrid import HybridSearchService

        cfg = HybridSearchConfig.from_env()

        if not getattr(cfg.elastic, "url", None):
            logger.info("BM25 search not configured (missing ELASTIC_URL)")
            return None

        svc = HybridSearchService(cfg)

        try:
            health = svc.health_check()
            es_ok = bool(health.get("elasticsearch"))
            if not es_ok:
                logger.warning(f"⚠️ Elasticsearch not healthy: {health}")
                return None
        except Exception as e:
            logger.warning(f"⚠️ BM25 health_check failed: {e}")
            return None

        logger.info("✅ BM25 search service initialized (Elasticsearch only)")

        health = svc.health_check()
        logger.warning(f"[BM25 health] raw={health}")

        return svc

    except Exception as e:
        logger.warning(f"⚠️ BM25 init failed, fallback to SQLite: {e}")
        return None


class IntegratedSearchPipeline:
    def __init__(self):
        self.timing = {}

        self._hybrid_service = _try_init_hybrid_service()
        self._use_hybrid = self._hybrid_service is not None

        self._bm25_service = _try_init_bm25_service()
        self._use_bm25 = self._bm25_service is not None

    @property
    def search_mode(self) -> str:
        if _env_bool("FORCE_SQLITE", False):
            return "sqlite_fallback"

        mode = _effective_search_mode()

        if mode == "bm25_only":
            return "bm25_only" if self._use_bm25 else "sqlite_fallback"

        if mode in ("dense_only", "hybrid", "auto"):
            if self._use_hybrid:
                return mode
            return "bm25_only" if self._use_bm25 else "sqlite_fallback"

        return "sqlite_fallback"

    async def search(
        self,
        query: str,
        store_id: str = "store_001",
        session_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        clarification_count: int = 0,
        input_type: str = "text",
        rerank_mode_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        request_id = str(uuid.uuid4())
        start_time = time.time()
        history = history or []

        result: Dict[str, Any] = {
            "request_id": request_id,
            "query": query,
            "store_id": store_id,
            "session_id": session_id or request_id,
            "is_in_scope": True,
            "intent": None,
            "top3": [],
            "top1_handover": None,
            "needs_clarification": False,
            "clarification_question": None,
            "clarification_options": [],
            "clarification_count": clarification_count,
            "is_fallback": False,
            "timing_ms": {},
            "metadata": {"search_mode": self.search_mode},
            "error": None,
        }

        # ✅ 관측값 박제(early return 포함)
        result["metadata"]["input_type"] = input_type
        result["metadata"]["rerank_mode_override"] = (rerank_mode_override or None)

        try:
            # 1) NLU
            nlu_start = time.time()
            nlu_result = await analyze_text(query, history=history)
            nlu_time = int((time.time() - nlu_start) * 1000)

            result["intent"] = nlu_result.intent.value
            result["metadata"]["nlu"] = {
                "slots": nlu_result.slots.model_dump(),
                "needs_clarification": nlu_result.needs_clarification,
                "token_usage": nlu_result.token_usage,
            }

            if nlu_result.intent.value == "UNSUPPORTED":
                result["is_in_scope"] = False
                result["message"] = "죄송합니다. 상품 찾기 외의 질문은 아직 답변하기 어렵습니다."
                result["timing_ms"] = {"nlu": nlu_time, "total": int((time.time() - start_time) * 1000)}
                return result

            if nlu_result.intent.value == "OTHER_INQUIRY":
                result["is_in_scope"] = False
                result["message"] = "일반 문의는 매장 직원에게 문의해 주세요."
                result["timing_ms"] = {"nlu": nlu_time, "total": int((time.time() - start_time) * 1000)}
                return result

            # 2) Keyword expansion
            expand_start = time.time()
            expand_cache_hit = False

            primary_keyword = nlu_result.slots.item or nlu_result.slots.query_rewrite or query
            search_keywords = [primary_keyword]

            cached_expansion = cache_get("expand", primary_keyword)
            if cached_expansion is not None:
                expanded_keywords = cached_expansion
                expand_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                expand_cache_hit = True
            else:
                if _vendor_allowed():
                    expanded_keywords, expand_usage = await expand_search_keywords(primary_keyword, return_usage=True)
                else:
                    expanded_keywords, expand_usage = [], {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                cache_set("expand", primary_keyword, expanded_keywords)

            search_keywords.extend(expanded_keywords[:3])
            search_keywords = list(dict.fromkeys(search_keywords))
            expand_time = int((time.time() - expand_start) * 1000)

            result["metadata"]["keywords"] = {
                "primary": primary_keyword,
                "expanded": search_keywords,
                "token_usage": expand_usage,
                "cache_hit": expand_cache_hit,
            }

            # 3) Search
            search_start = time.time()
            search_cache_hit = False

            cached_search = cache_get("search", search_keywords)
            if cached_search is not None:
                candidates = cached_search
                logger.warning(
                    "[CACHE HIT] search key=%r size=%s",
                    search_keywords,
                    len(cached_search) if hasattr(cached_search, "__len__") else "na",
                )
                search_cache_hit = True
            else:
                if _env_bool("FORCE_SQLITE", False):
                    candidates = self._sqlite_search(search_keywords)
                    result["metadata"]["search"] = {
                        **result["metadata"].get("search", {}),
                        "mode": "sqlite_fallback",
                        "forced_sqlite": True,
                    }
                else:
                    mode = _effective_search_mode()

                    try:
                        if mode == "bm25_only":
                            if self._use_bm25:
                                candidates = self._bm25_search(search_keywords, result, top_k=10)
                            else:
                                candidates = self._sqlite_search(search_keywords)

                        elif mode in ("dense_only", "hybrid"):
                            if not self._use_hybrid:
                                candidates = self._bm25_search(search_keywords, result, top_k=10) if self._use_bm25 else self._sqlite_search(search_keywords)
                            elif not _vendor_allowed():
                                candidates = self._bm25_search(search_keywords, result, top_k=10) if self._use_bm25 else self._sqlite_search(search_keywords)
                            else:
                                query_text = " ".join(search_keywords)
                                sr = self._hybrid_service.search(query_text, top_k=10, mode=mode)

                                candidates = []
                                for d in sr.docs:
                                    payload = getattr(d, "payload", {}) or {}
                                    title = payload.get("title") or payload.get("name") or getattr(d, "title", None) or getattr(d, "doc_id", "")
                                    text = payload.get("text") or getattr(d, "text", "") or ""
                                    candidates.append(
                                        {
                                            "id": getattr(d, "doc_id", None) or payload.get("doc_id") or title,
                                            "name": title,
                                            "text": text,
                                            "searchable_desc": payload.get("bm25_text", text) or text,
                                            "category": payload.get("category") or getattr(d, "category", None),
                                            "price": payload.get("price", 0),
                                            "image_url": payload.get("image_url", ""),
                                            "score": getattr(d, "score", None),
                                            "source": getattr(d, "source", "hybrid"),
                                        }
                                    )

                                result["metadata"]["search"] = {
                                    "hybrid_timing": sr.timing_ms,
                                    "hybrid_metadata": sr.metadata,
                                    "mode": mode,
                                }

                        else:
                            if self._use_hybrid and _vendor_allowed():
                                query_text = " ".join(search_keywords)
                                sr = self._hybrid_service.search(query_text, top_k=10, mode="hybrid")
                                candidates = []
                                for d in sr.docs:
                                    payload = getattr(d, "payload", {}) or {}
                                    title = payload.get("title") or payload.get("name") or getattr(d, "title", None) or getattr(d, "doc_id", "")
                                    text = payload.get("text") or getattr(d, "text", "") or ""
                                    candidates.append(
                                        {
                                            "id": getattr(d, "doc_id", None) or payload.get("doc_id") or title,
                                            "name": title,
                                            "text": text,
                                            "searchable_desc": payload.get("bm25_text", text) or text,
                                            "category": payload.get("category") or getattr(d, "category", None),
                                            "price": payload.get("price", 0),
                                            "image_url": payload.get("image_url", ""),
                                            "score": getattr(d, "score", None),
                                            "source": getattr(d, "source", "hybrid"),
                                        }
                                    )
                                result["metadata"]["search"] = {
                                    "hybrid_timing": sr.timing_ms,
                                    "hybrid_metadata": sr.metadata,
                                    "mode": "hybrid",
                                }
                            else:
                                candidates = self._bm25_search(search_keywords, result, top_k=10) if self._use_bm25 else self._sqlite_search(search_keywords)

                    except Exception as e:
                        logger.exception("Search pipeline error in mode=%s: %s", mode, e)
                        candidates = self._bm25_search(search_keywords, result, top_k=10) if self._use_bm25 else self._sqlite_search(search_keywords)

                cache_set("search", search_keywords, candidates)

            search_time = int((time.time() - search_start) * 1000)

            result["metadata"]["search"] = {
                **result["metadata"].get("search", {}),
                "mode": self.search_mode,
                "candidates_count": len(candidates),
                "keywords_used": search_keywords,
                "cache_hit": search_cache_hit,
            }

            # 4) Ambiguity
            ambiguity_start = time.time()
            category_spread = calculate_category_spread(candidates)

            ambiguity_result = detect_ambiguity(
                item=nlu_result.slots.item,
                attrs=nlu_result.slots.attrs,
                candidates_count=len(candidates),
                category_spread=category_spread,
                nlu_needs_clarification=nlu_result.needs_clarification,
            )

            if self.search_mode == "bm25_only" and len(candidates) >= 3:
                majors = []
                for c in candidates[:3]:
                    major = c.get("category") or match_product_to_category(c["name"])[0]
                    majors.append(major)
                if len(set(majors)) == 1:
                    ambiguity_result.is_ambiguous = False

            ambiguity_time = int((time.time() - ambiguity_start) * 1000)

            result["metadata"]["ambiguity"] = {
                "type": ambiguity_result.ambiguity_type.value,
                "is_ambiguous": ambiguity_result.is_ambiguous,
                "confidence": ambiguity_result.confidence,
                "reason": ambiguity_result.reason,
                "category_spread": category_spread,
            }

            demo_bypass = (os.getenv("DEMO_CLARIFY_BYPASS") or "").strip().lower() in ("1", "true")

            if ambiguity_result.is_ambiguous:
                if demo_bypass and clarification_count >= 1:
                    ambiguity_result.is_ambiguous = False
                else:
                    if should_fallback(clarification_count):
                        result["is_fallback"] = True
                        result["message"] = "정확한 상품을 찾기 어려워 가장 관련 있는 상품을 안내해 드립니다."
                    else:
                        options = generate_clarification_options(candidates, item=nlu_result.slots.item)
                        question = build_clarification_question(nlu_result.slots.item, options)

                        result["needs_clarification"] = True
                        result["clarification_question"] = question
                        result["clarification_options"] = options
                        result["clarification_count"] = clarification_count + 1

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
            
            selected_id: Optional[str] = None
            rerank_time = 0
                
            # 5) Rerank (guard)
            mode = (os.getenv("SEARCH_MODE") or "").strip().lower()
            
            env_rerank_mode = (os.getenv("RERANK_MODE") or "").strip().lower()
            vendor_enabled = (os.getenv("VENDOR_ENABLED") or "").strip().lower() == "true"
            
            req_override = (rerank_mode_override or "").strip().lower()
            rerank_mode = req_override or env_rerank_mode
            
            # voice/stt는 override가 없으면 local로 강제(Timeout 방지)
            if (not req_override) and (input_type != "text"):
                rerank_mode = "local"
            
            def _should_vendor_rerank_text(cands):
                # 애매하면 True → vendor rerank 허용
                if not cands or len(cands) < 2:
                    return False
            
                # (A) 카테고리 분산(top3 대분류가 갈라지면 애매)
                majors = []
                for c in cands[:3]:
                    major = c.get("category") or match_product_to_category(c.get("name", ""))[0]
                    majors.append(major)
                if len(set(majors)) >= 2:
                    return True
            
                # (B) 점수 근접(top1/top2 점수차가 작으면 애매)
                def _score(x):
                    try:
                        return float(x)
                    except Exception:
                        return None
            
                s1 = _score(cands[0].get("score"))
                s2 = _score(cands[1].get("score"))
                if s1 is None or s2 is None or s1 == 0:
                    return False
            
                rel_gap = abs(s1 - s2) / (abs(s1) + 1e-9)
                thr = float(os.getenv("RERANK_VENDOR_REL_GAP_MAX", "0.08") or "0.08")  # 8%
                return rel_gap <= thr
            
            # ✅ text에서 vendor일 때만 게이팅 적용(override=vendor면 무조건 vendor)
            if (
                rerank_mode in ("vendor", "live")
                and vendor_enabled
                and input_type == "text"
                and req_override != "vendor"
            ):
                if not _should_vendor_rerank_text(candidates):
                    rerank_mode = "local"
            
            result["metadata"]["_debug_rerank_guard"] = {
                "mode": mode,
                "rerank_mode": rerank_mode,
                "env_rerank_mode": env_rerank_mode,
                "req_override": req_override,
                "vendor_enabled": vendor_enabled,
                "input_type": input_type,
            }
            
            # vendor 강제인데 실제 벤더 호출이 불가능하면 local로 강등(메타에 이유 남김)
            if rerank_mode in ("vendor", "live") and (not _vendor_allowed()):
                result["metadata"]["_debug_rerank_guard"]["forced_downgrade"] = "vendor_not_allowed"
                rerank_mode = "local"
            
            # 5-1) Rerank (execute)
            try:
                # 기본: rerank 스킵 메타도 남겨서 "왜 비었는지" 추적 가능하게
                result["metadata"]["rerank"] = {
                    "mode": rerank_mode,
                    "skipped": True,
                    "reason": "not_executed_yet",
                    "selected_id": None,
                    "latency_ms": 0,
                }

                # off면 그대로 스킵
                if rerank_mode in ("off", "none", ""):
                    pass

                # local / vendor 실행
                else:
                    rerank_start = time.time()
                    
                    logger.warning("[RERANK INPUT] mode=%s timeout=%s cand0_keys=%s",
                    rerank_mode, os.getenv("RERANK_TIMEOUT", "6.0"),
                    list((candidates[0] or {}).keys()) if candidates else None)
                    
                    rr = rerank_candidates(
                        user_query=query,
                        candidates=candidates,
                        timeout=float(os.getenv("RERANK_TIMEOUT", "6.0") or "6.0"),
                        mode_override=rerank_mode,
                    )
                
                    rerank_time = int((time.time() - rerank_start) * 1000)

                    # rr 가 dict든 pydantic이든 방어적으로 처리
                    selected_id = None
                    reranked = None
                    rr_meta = {}

                    if isinstance(rr, dict):
                        selected_id = rr.get("selected_id") or rr.get("top1_id")
                        reranked = rr.get("candidates") or rr.get("reranked") or rr.get("results")
                        rr_meta = rr.get("metadata") or {}
                    else:
                        selected_id = getattr(rr, "selected_id", None) or getattr(rr, "top1_id", None)
                        reranked = getattr(rr, "candidates", None) or getattr(rr, "reranked", None) or getattr(rr, "results", None)
                        rr_meta = getattr(rr, "metadata", {}) or {}

                    if reranked:
                        candidates = reranked

                    result["metadata"]["rerank"] = {
                        "mode": rerank_mode,
                        "skipped": False,
                        "selected_id": selected_id,
                        "latency_ms": rerank_time,
                        "vendor_used": (rerank_mode in ("vendor", "live")),
                        "details": rr_meta,
                    }

            except Exception as e:
                logger.exception("Rerank failed: %s", e)
                # rerank 실패해도 검색 결과는 계속 반환
                result["metadata"]["rerank"] = {
                    "mode": rerank_mode,
                    "skipped": True,
                    "reason": f"error:{type(e).__name__}",
                    "selected_id": selected_id,
                    "latency_ms": rerank_time,
                }

            # 6) Format top3
            location_start = time.time()
            top3 = self._format_top3(candidates[:3], selected_id=selected_id)
            location_time = int((time.time() - location_start) * 1000)

            result["top3"] = top3
            if not result.get("message"):
                result["message"] = f"'{query}' 관련 상품 {len(top3)}개를 찾았습니다."

            result["timing_ms"] = {
                "nlu": nlu_time,
                "expand": expand_time,
                "search": search_time,
                "ambiguity": ambiguity_time,
                "rerank": rerank_time,
                "location": location_time,
                "total": int((time.time() - start_time) * 1000),
            }

            return result

        except Exception as e:
            logger.error(f"Search pipeline error: {e}", exc_info=True)
            result["error"] = str(e)
            result["message"] = "검색 중 오류가 발생했습니다. 다시 시도해 주세요."
            result["timing_ms"] = {"total": int((time.time() - start_time) * 1000)}
            return result

    def _format_top3(self, candidates: List[Dict[str, Any]], selected_id: Optional[str] = None) -> List[Dict[str, Any]]:
        top3 = []
        for idx, c in enumerate(candidates[:3]):
            major, middle = match_product_to_category(c["name"])
            product_data = {
                "product_id": c["id"],
                "name": c["name"],
                "price": str(c.get("price", 0)),
                "category_major": c.get("category", major),
                "category_middle": middle,
                "location_text": f"{c.get('category', major)} > {middle}",
                "image_url": c.get("image_url"),
                "rank": idx + 1,
                "is_top1": False,
            }
            top3.append(product_data)

        if selected_id is not None:
            for i, p in enumerate(top3):
                if str(p["product_id"]) == str(selected_id):
                    picked = top3.pop(i)
                    picked["is_top1"] = True
                    picked["rank"] = 1
                    top3.insert(0, picked)
                    break

        if top3 and not any(p["is_top1"] for p in top3):
            top3[0]["is_top1"] = True

        for i, p in enumerate(top3):
            p["rank"] = i + 1

        return top3[:3]

    def _bm25_search(self, keywords: List[str], result: Dict[str, Any], top_k: int = 10) -> List[Dict[str, Any]]:
        query_text = " ".join(keywords or [])
        logger.warning("[BM25] CALL query_text=%r top_k=%s", query_text, top_k)

        sr = self._bm25_service.search(query_text, top_k=top_k, mode="bm25_only")

        candidates: List[Dict[str, Any]] = []
        for doc in sr.docs:
            payload = getattr(doc, "payload", {}) or {}
            candidates.append(
                {
                    "id": doc.doc_id,
                    "name": getattr(doc, "title", None) or doc.doc_id,
                    "text": getattr(doc, "text", "") or "",
                    "searchable_desc": payload.get("bm25_text", getattr(doc, "text", "") or ""),
                    "category": getattr(doc, "category", None) or payload.get("category"),
                    "price": payload.get("price", 0),
                    "score": getattr(doc, "score", None),
                    "source": getattr(doc, "source", "elastic"),
                }
            )

        result["metadata"]["search"] = {
            "hybrid_timing": sr.timing_ms,
            "hybrid_metadata": sr.metadata,
            "mode": "bm25_only",
        }
        return candidates

    def _sqlite_search(self, keywords: List[str]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for keyword in keywords:
            found = search_products(keyword)
            candidates.extend(found)
            if len(candidates) >= 10:
                break

        seen_ids = set()
        unique_candidates = []
        for c in candidates:
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                unique_candidates.append(c)

        return unique_candidates[:10]


_pipeline: Optional[IntegratedSearchPipeline] = None


def get_pipeline() -> IntegratedSearchPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = IntegratedSearchPipeline()
    return _pipeline