"""
backend/ml/rerank_service.py — Thin ML rerank service layer.

Exposes RerankService with RERANK_MODE=mock|vendor|simulated|local switch.
- mock:      deterministic first-candidate selection (no LLM, fast)
- vendor:    delegates to backend.logic.reranker.rerank_candidates (Gemini LLM)
             controlled by VENDOR_SAMPLE_RATE (0.0-1.0, default 1.0)
- simulated: env-driven latency/error simulation, no external calls
- local:     deterministic token-overlap scoring, no external calls

Response always includes: selected_id, reason, confidence, latency_ms, is_fallback, error_type
error_type values: RATE_LIMIT | TIMEOUT | VENDOR_ERROR | None
"""

import os
import time
import random
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

VALID_MODES = ("mock", "vendor", "simulated", "local")
DEFAULT_MODE = "simulated"


class RerankService:
    """Thin wrapper around the M2 reranker with mock/vendor/simulated/local switch."""

    def __init__(self, mode: Optional[str] = None):
        if mode is None:
            mode = os.environ.get("RERANK_MODE", DEFAULT_MODE).strip()
        else:
            mode = mode.strip()
        if mode not in VALID_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of {VALID_MODES}"
            )
        self.mode = mode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Rerank candidates and return a standardised response dict.

        Returns:
            {
                "selected_id": str | None,
                "reason": str,
                "confidence": float,
                "latency_ms": int,
                "is_fallback": bool,
                "error_type": str | None,   # RATE_LIMIT | TIMEOUT | VENDOR_ERROR | None
            }
        """
        if not candidates:
            return {
                "selected_id": None,
                "reason": "후보 상품이 없습니다.",
                "confidence": 0.0,
                "latency_ms": 0,
                "is_fallback": False,
                "error_type": None,
            }

        if self.mode == "mock":
            return self._mock_rerank(query, candidates)
        elif self.mode == "vendor":
            return self._vendor_rerank(query, candidates, timeout)
        elif self.mode == "simulated":
            return self._simulated_rerank(query, candidates)
        elif self.mode == "local":
            return self._local_rerank(query, candidates)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    # ------------------------------------------------------------------
    # Mock mode — deterministic first-candidate, no LLM
    # ------------------------------------------------------------------

    def _mock_rerank(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        selected = candidates[0]
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "selected_id": str(selected["id"]),
            "reason": f"Mock 선택: {selected.get('name', '')}",
            "confidence": 0.85,
            "latency_ms": elapsed_ms,
            "is_fallback": False,
            "error_type": None,
        }

    # ------------------------------------------------------------------
    # Vendor mode — delegates to existing Gemini reranker
    # Controlled by VENDOR_SAMPLE_RATE (0.0-1.0)
    # ------------------------------------------------------------------

    def _vendor_rerank(
        self, query: str, candidates: List[Dict[str, Any]], timeout: float
    ) -> Dict[str, Any]:
        sample_rate = float(os.environ.get("VENDOR_SAMPLE_RATE", "1.0"))

        # If sample rate blocks this call, use local fallback
        if sample_rate <= 0.0 or random.random() > sample_rate:
            result = self._local_rerank(query, candidates)
            result["is_fallback"] = True
            result["reason"] = f"Vendor skipped (sample_rate={sample_rate}): " + result["reason"]
            return result

        from backend.logic.reranker import rerank_candidates

        start = time.perf_counter()
        try:
            raw = rerank_candidates(query, candidates, timeout=timeout)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                "selected_id": raw.get("selected_id"),
                "reason": raw.get("reason", ""),
                "confidence": raw.get("confidence", 0.0),
                "latency_ms": elapsed_ms,
                "is_fallback": False,
                "error_type": None,
            }
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.error("Vendor rerank failed: %s", exc)
            # Fallback: use local scoring
            result = self._local_rerank(query, candidates)
            result["latency_ms"] = elapsed_ms
            result["is_fallback"] = True
            result["error_type"] = "VENDOR_ERROR"
            return result

    # ------------------------------------------------------------------
    # Simulated mode — env-driven latency/error simulation, no external calls
    # ------------------------------------------------------------------

    def _simulated_rerank(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        # Read simulation parameters from env
        target_ms = float(os.environ.get("SIM_TARGET_LATENCY_MS", "300"))
        jitter_ms = float(os.environ.get("SIM_JITTER_MS", "150"))
        timeout_rate = float(os.environ.get("SIM_TIMEOUT_RATE", "0.01"))
        rate_limit_rate = float(os.environ.get("SIM_RATE_LIMIT_RATE", "0.02"))
        vendor_error_rate = float(os.environ.get("SIM_VENDOR_ERROR_RATE", "0.005"))

        # Simulate latency
        simulated_latency_ms = max(0, target_ms + random.uniform(-jitter_ms, jitter_ms))
        sleep_sec = simulated_latency_ms / 1000.0

        start = time.perf_counter()
        time.sleep(sleep_sec)

        # Determine if an error should be injected (priority: timeout > rate_limit > vendor_error)
        roll = random.random()
        error_type = None
        if roll < timeout_rate:
            error_type = "TIMEOUT"
        elif roll < timeout_rate + rate_limit_rate:
            error_type = "RATE_LIMIT"
        elif roll < timeout_rate + rate_limit_rate + vendor_error_rate:
            error_type = "VENDOR_ERROR"

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if error_type is not None:
            # Error path: fallback to local scoring
            result = self._local_rerank(query, candidates)
            result["latency_ms"] = elapsed_ms
            result["is_fallback"] = True
            result["error_type"] = error_type
            return result

        # Success path: use local scoring as the "simulated vendor" result
        result = self._local_rerank(query, candidates)
        result["latency_ms"] = elapsed_ms
        return result

    # ------------------------------------------------------------------
    # Local mode — deterministic token-overlap scoring, no external calls
    # ------------------------------------------------------------------

    def _local_rerank(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        start = time.perf_counter()

        query_tokens = set(query.lower().split())

        best_score = -1
        best_candidate = candidates[0]

        for c in candidates:
            name = c.get("name", "").lower()
            desc = (c.get("desc", "") or "").lower()
            category = (c.get("category", "") or "").lower()
            text = f"{name} {desc} {category}"
            text_tokens = set(text.split())

            # Token overlap score
            score = len(query_tokens & text_tokens)

            # Exact substring bonus
            if query.lower() in name:
                score += 3
            elif query.lower() in text:
                score += 1

            if score > best_score:
                best_score = score
                best_candidate = c

        # Normalise confidence to [0, 1]
        max_possible = len(query_tokens) + 3  # max token matches + exact match bonus
        confidence = min(1.0, best_score / max(max_possible, 1)) if best_score > 0 else 0.1

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return {
            "selected_id": str(best_candidate["id"]),
            "reason": f"Local 토큰매칭: {best_candidate.get('name', '')} (score={best_score})",
            "confidence": round(confidence, 4),
            "latency_ms": elapsed_ms,
            "is_fallback": False,
            "error_type": None,
        }
