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


def _get_api_key() -> Optional[str]:
    google = _env_str("GOOGLE_API_KEY", "")
    gemini = _env_str("GEMINI_API_KEY", "")
    if google and gemini and google != gemini:
        logger.warning("Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY.")
    return google or gemini or None


def _make_client():
    # SAFE_MODE에서 외부 호출 금지 (런타임 체크)
    if _env_bool("SAFE_MODE", False):
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
    mode_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    후보들을 rerank해서 top1을 선택.
    """
    start_total = time.time()

    if not candidates:
        return {"selected_id": None, "reason": "후보 없음", "confidence": 0.0, "latency": 0}

    # 0) SAFE_MODE=1이면 외부호출 금지(무조건 로컬)  (런타임 체크)
    if _env_bool("SAFE_MODE", False):
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = "SAFE_MODE(local): " + out.get("reason", "")
        return out

    # 1) 모드 결정: override > env (빈 문자열이면 무시)
    mode = (mode_override or "").strip().lower()
    if not mode:
        mode = _env_str("RERANK_MODE", "local").strip().lower() or "local"

    # 2) local/off 계열
    if mode in ("off", "none", "disabled", "false", "0", "local"):
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = f"{mode}(local): " + out.get("reason", "")
        return out

    # 3) mock (초고속 데모)
    if mode == "mock":
        first = candidates[0]
        selected_id = first.get("id") or first.get("product_id") or first.get("doc_id")
        return {
            "selected_id": selected_id,
            "reason": "mock: 첫 후보 선택",
            "confidence": 1.0 / max(1, len(candidates)),
            "latency": int((time.time() - start_total) * 1000),
        }

    # 4) simulated (지연만 흉내 + 로컬 결정)
    if mode == "simulated":
        time.sleep(float(_env_str("RERANK_SIMULATED_LATENCY_SEC", "0.3") or "0.3"))
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = "simulated(local): " + out.get("reason", "")
        out["latency"] = int((time.time() - start_total) * 1000)
        return out

    # 5) vendor/live만 LLM 허용
    if mode not in ("vendor", "live"):
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = f"unknown_mode({mode}): " + out.get("reason", "")
        return out

    vendor_enabled = _env_bool("VENDOR_ENABLED", False)
    if not vendor_enabled:
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = "vendor_disabled(local): " + out.get("reason", "")
        return out

    # (A) Early-exit (RERANK_EARLY_HIT=0이면 OFF)
    q = (user_query or "").strip().lower()
    toks = [t for t in re.split(r"[\s\W]+", q) if t][: int(_env_str("RERANK_EARLY_TOKS", "6") or "6")]
    top1_name = str(candidates[0].get("name") or candidates[0].get("title") or "").lower()
    hit = sum(1 for t in toks if t and t in top1_name)
    early_hit = int(_env_str("RERANK_EARLY_HIT", "2") or "2")

    if early_hit > 0 and hit >= early_hit:
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = f"early-exit(local hit={hit}/{early_hit}): " + out.get("reason", "")
        out["latency"] = int((time.time() - start_total) * 1000)
        return out

    # (B) optional gate: 애매할 때만 LLM
    gate_on = _env_bool("RERANK_VENDOR_GATE", False)

    def _as_float(x) -> Optional[float]:
        try:
            if x is None:
                return None
            return float(x)
        except Exception:
            return None

    if gate_on and len(candidates) >= 2:
        s1 = _as_float(candidates[0].get("score"))
        s2 = _as_float(candidates[1].get("score"))
        if s1 is not None and s2 is not None and abs(s1) > 1e-9:
            rel_gap = abs(s1 - s2) / (abs(s1) + 1e-9)
            thr = float(_env_str("RERANK_VENDOR_REL_GAP_MAX", "0.08") or "0.08")
            if rel_gap > thr:
                out = _fallback_rerank(user_query, candidates)
                out["reason"] = f"gate_skip_llm(local gap={rel_gap:.4f}>{thr}): " + out.get("reason", "")
                out["latency"] = int((time.time() - start_total) * 1000)
                return out

    # (C) LLM 호출
    client = _make_client()
    if client is None:
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = "no_client(local): " + out.get("reason", "")
        out["latency"] = int((time.time() - start_total) * 1000)
        return out

    try:
        return _llm_rerank(client, user_query, candidates, timeout)
    except Exception:
        logger.exception("LLM rerank failed")
        out = _fallback_rerank(user_query, candidates)
        out["reason"] = "llm_failed(local): " + out.get("reason", "")
        out["latency"] = int((time.time() - start_total) * 1000)
        return out


def _llm_rerank(client, user_query: str, candidates: List[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
    start = time.time()

    GEMINI_MODEL = _env_str("GEMINI_MODEL", _env_str("GEMINI_MODEL_NAME", "gemini-2.0-flash")) or "gemini-2.0-flash"

    topn = int(_env_str("RERANK_VENDOR_TOPN", "10") or "10")
    topn = max(1, min(topn, 30))

    logger.warning("[RERANK][LLM_CALL] model=%s topn=%s query=%r", GEMINI_MODEL, topn, user_query)

    compact: List[Dict[str, Any]] = []
    for c in candidates[:topn]:
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
        return client.models.generate_content(model=GEMINI_MODEL, contents=prompt)

    fut = _RERANK_EXECUTOR.submit(_call)
    resp = fut.result(timeout=timeout)

    raw = (getattr(resp, "text", "") or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    logger.warning("[RERANK][LLM_DONE] raw_head=%r", raw[:120])

    data = json.loads(raw)
    selected_id = data.get("selected_id")
    reason = str(data.get("reason", "")).strip()
    try:
        conf = float(data.get("confidence", 0.0))
    except Exception:
        conf = 0.0

    latency = int((time.time() - start) * 1000)
    logger.warning("[RERANK][LLM_DONE] latency_ms=%s selected_id=%r", latency, selected_id)

    return {
        "selected_id": selected_id,
        "reason": reason,
        "confidence": max(0.0, min(conf, 1.0)),
        "latency": latency,
    }


def _fallback_rerank(user_query: str, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
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