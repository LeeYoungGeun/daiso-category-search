"""
backend/logic/reranker.py

- 후보 리스트를 rerank해서 top1을 선택
- RERANK_MODE=local/mock/simulated/vendor(live) 스위치
- SAFE_MODE=1이면 외부 LLM 호출 금지(무조건 로컬)
- GEMINI_MODEL 환경변수로 generateContent 모델 선택

주의: 이 모듈은 비용 절감/안정성을 위해 "외부 호출"을 강하게 게이트한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_RERANK_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rerank")


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip()


SAFE_MODE: bool = _env_bool("SAFE_MODE", False)
GEMINI_MODEL: str = _env_str("GEMINI_MODEL", _env_str("GEMINI_MODEL_NAME", "gemini-2.0-flash")) or "gemini-2.0-flash"


def _get_api_key() -> Optional[str]:
    google = _env_str("GOOGLE_API_KEY", "")
    gemini = _env_str("GEMINI_API_KEY", "")
    if google and gemini and google != gemini:
        print("Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY.")
    return google or gemini or None


def _make_client():
    if SAFE_MODE:
        return None
    api_key = _get_api_key()
    if not api_key:
        logger.warning("No GOOGLE_API_KEY/GEMINI_API_KEY, reranker will use fallback")
        return None
    try:
        from google import genai  # type: ignore
    except Exception:
        logger.warning("google-genai not installed, reranker will use fallback")
        return None
    return genai.Client(api_key=api_key)


def rerank_candidates(
    user_query: str,
    candidates: List[Dict[str, Any]],
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    후보들을 rerank해서 top1을 선택.
    반환:
      {
        "selected_id": <id or None>,
        "reason": <string>,
        "confidence": 0~1,
        "latency": ms
      }
    """
    if not candidates:
        return {"selected_id": None, "reason": "후보 없음", "confidence": 0.0, "latency": 0}

    # SAFE_MODE=1이면 무조건 로컬
    if SAFE_MODE:
        return _fallback_rerank(user_query, candidates)

    client = _make_client()
    if client is None:
        return _fallback_rerank(user_query, candidates)

    try:
        return _llm_rerank(client, user_query, candidates, timeout)
    except Exception as e:
        logger.error(f"LLM rerank failed: {e}")
        return _fallback_rerank(user_query, candidates)


def _llm_rerank(client, user_query: str, candidates: List[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
    """
    Gemini generate_content 기반 rerank.
    """
    start = time.time()

    # 후보를 compact하게 전달 (토큰 절약)
    compact = []
    for c in candidates[:30]:
        compact.append(
            {
                "id": c.get("id") or c.get("product_id") or c.get("doc_id"),
                "name": c.get("name") or c.get("title") or "",
                "category": c.get("category") or c.get("category_middle") or c.get("category_major") or "",
                "price": c.get("price"),
            }
        )

    prompt = f"""
너는 검색 결과 reranker다. 사용자 질의에 가장 잘 맞는 후보 1개를 골라라.
반드시 아래 JSON만 출력해라(다른 텍스트 금지).

출력 스키마:
{{
  "selected_id": "<id or null>",
  "reason": "<짧은 이유>",
  "confidence": 0~1
}}

사용자 질의: "{user_query}"
후보 목록(JSON):
{json.dumps(compact, ensure_ascii=False)}
""".strip()

    def _call():
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return resp

    fut = _RERANK_EXECUTOR.submit(_call)
    resp = fut.result(timeout=timeout)

    raw = (getattr(resp, "text", "") or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)
    selected_id = data.get("selected_id")
    reason = str(data.get("reason", "")).strip()
    try:
        conf = float(data.get("confidence", 0.0))
    except Exception:
        conf = 0.0

    latency = int((time.time() - start) * 1000)
    return {"selected_id": selected_id, "reason": reason, "confidence": max(0.0, min(conf, 1.0)), "latency": latency}


def _fallback_rerank(user_query: str, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    외부 LLM이 없을 때의 로컬 rerank.
    - query 단어가 name/category에 많이 겹치는 후보를 선택
    - tie-break: rank/score 있으면 활용
    """
    start = time.time()

    q = (user_query or "").strip().lower()
    toks = [t for t in re.split(r"[\s\W]+", q) if t][:10]

    def score(c: Dict[str, Any]) -> float:
        name = str(c.get("name") or c.get("title") or "").lower()
        cat = str(c.get("category") or c.get("category_middle") or c.get("category_major") or "").lower()
        text = f"{name} {cat}"
        hit = sum(1 for t in toks if t and t in text)
        base = float(c.get("score") or 0.0)
        rank = float(c.get("rank") or 0.0)
        return hit * 10.0 + base - rank * 0.01

    best = max(candidates, key=score)
    latency = int((time.time() - start) * 1000)

    selected_id = best.get("id") or best.get("product_id") or best.get("doc_id")
    reason = "키워드 매칭 기반 선택"
    conf = 1.0 / max(1, len(candidates))
    return {"selected_id": selected_id, "reason": reason, "confidence": conf, "latency": latency}
