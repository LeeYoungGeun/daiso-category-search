"""
ML Rerank v2.1.1 Tests — TDD Red Phase

Tests for:
1. simulated mode: latency simulation, error injection, is_fallback on error
2. local mode: deterministic token-matching rerank, confidence 0-1
3. vendor sampling: VENDOR_SAMPLE_RATE=0 blocks vendor calls
4. default mode is now 'simulated'
5. error_type standardisation: RATE_LIMIT | TIMEOUT | VENDOR_ERROR | NONE
"""

import pytest
import sys
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

CANDIDATES_3 = [
    {"id": "1", "name": "스텐 채반", "desc": "튀김/면 요리용", "category": "주방용품"},
    {"id": "2", "name": "세탁망 원형", "desc": "세탁기용 망", "category": "생활용품"},
    {"id": "3", "name": "튀김가루 1kg", "desc": "식재료", "category": "식품"},
]

CANDIDATES_2 = [
    {"id": "10", "name": "파란 볼펜", "desc": "필기구", "category": "문구"},
    {"id": "11", "name": "빨간 볼펜", "desc": "필기구", "category": "문구"},
]


# ============================================================================
# 1. simulated mode — latency simulation + error injection
# ============================================================================

class TestSimulatedMode:
    """simulated mode: no external calls, env-driven latency/error simulation."""

    def test_simulated_mode_accepted(self):
        """RerankService should accept mode='simulated' without error."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="simulated")
        assert svc.mode == "simulated"

    def test_simulated_returns_valid_schema(self):
        """simulated mode response must have all required fields."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="simulated")
        result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
        assert "selected_id" in result
        assert "reason" in result
        assert "confidence" in result
        assert "latency_ms" in result
        assert "is_fallback" in result
        assert "error_type" in result

    def test_simulated_no_external_calls(self):
        """simulated mode must NOT call backend.logic.reranker."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="simulated")
        with patch("backend.logic.reranker.rerank_candidates") as mock_vendor:
            svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            mock_vendor.assert_not_called()

    def test_simulated_latency_within_range(self):
        """With SIM_TARGET_LATENCY_MS=100, SIM_JITTER_MS=50, latency should be 50-150ms."""
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "100",
            "SIM_JITTER_MS": "50",
            "SIM_TIMEOUT_RATE": "0",
            "SIM_RATE_LIMIT_RATE": "0",
            "SIM_VENDOR_ERROR_RATE": "0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            # latency_ms should be roughly in [50, 150] range
            assert result["latency_ms"] >= 40  # allow small timing variance
            assert result["latency_ms"] <= 200

    def test_simulated_error_timeout(self):
        """With SIM_TIMEOUT_RATE=1.0, every call should produce TIMEOUT error."""
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "10",
            "SIM_JITTER_MS": "0",
            "SIM_TIMEOUT_RATE": "1.0",
            "SIM_RATE_LIMIT_RATE": "0",
            "SIM_VENDOR_ERROR_RATE": "0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            assert result["error_type"] == "TIMEOUT"
            assert result["is_fallback"] is True
            assert result["selected_id"] is not None  # fallback still returns something

    def test_simulated_error_rate_limit(self):
        """With SIM_RATE_LIMIT_RATE=1.0, every call should produce RATE_LIMIT error."""
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "10",
            "SIM_JITTER_MS": "0",
            "SIM_TIMEOUT_RATE": "0",
            "SIM_RATE_LIMIT_RATE": "1.0",
            "SIM_VENDOR_ERROR_RATE": "0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            assert result["error_type"] == "RATE_LIMIT"
            assert result["is_fallback"] is True

    def test_simulated_error_vendor_error(self):
        """With SIM_VENDOR_ERROR_RATE=1.0, every call should produce VENDOR_ERROR."""
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "10",
            "SIM_JITTER_MS": "0",
            "SIM_TIMEOUT_RATE": "0",
            "SIM_RATE_LIMIT_RATE": "0",
            "SIM_VENDOR_ERROR_RATE": "1.0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            assert result["error_type"] == "VENDOR_ERROR"
            assert result["is_fallback"] is True

    def test_simulated_no_error_returns_none_error_type(self):
        """With all error rates=0, error_type should be None (or 'NONE')."""
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "10",
            "SIM_JITTER_MS": "0",
            "SIM_TIMEOUT_RATE": "0",
            "SIM_RATE_LIMIT_RATE": "0",
            "SIM_VENDOR_ERROR_RATE": "0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            assert result["error_type"] is None
            assert result["is_fallback"] is False

    def test_simulated_fallback_uses_local_scoring(self):
        """When simulated error occurs, fallback should use local keyword scoring."""
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "10",
            "SIM_JITTER_MS": "0",
            "SIM_TIMEOUT_RATE": "1.0",
            "SIM_RATE_LIMIT_RATE": "0",
            "SIM_VENDOR_ERROR_RATE": "0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            # Should still pick a candidate via local fallback
            assert result["selected_id"] in ("10", "11")
            assert 0.0 <= result["confidence"] <= 1.0


# ============================================================================
# 2. local mode — deterministic token-matching rerank
# ============================================================================

class TestLocalMode:
    """local mode: deterministic token-overlap scoring, no external calls."""

    def test_local_mode_accepted(self):
        """RerankService should accept mode='local'."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        assert svc.mode == "local"

    def test_local_returns_valid_schema(self):
        """local mode response must have all required fields."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        result = svc.rerank(query="파란 볼펜", candidates=CANDIDATES_2)
        assert "selected_id" in result
        assert "reason" in result
        assert "confidence" in result
        assert "latency_ms" in result
        assert "is_fallback" in result
        assert "error_type" in result

    def test_local_deterministic(self):
        """Same input must produce same output every time."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        r1 = svc.rerank(query="파란 볼펜", candidates=CANDIDATES_2)
        r2 = svc.rerank(query="파란 볼펜", candidates=CANDIDATES_2)
        assert r1["selected_id"] == r2["selected_id"]
        assert r1["confidence"] == r2["confidence"]

    def test_local_prefers_matching_candidate(self):
        """local mode should prefer candidate whose name matches query tokens."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        result = svc.rerank(query="파란 볼펜", candidates=CANDIDATES_2)
        # "파란 볼펜" should match "파란 볼펜" (id=10) better than "빨간 볼펜" (id=11)
        assert result["selected_id"] == "10"

    def test_local_confidence_range(self):
        """local mode confidence must be in [0.0, 1.0]."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        result = svc.rerank(query="튀김 건질 때 쓰는 거", candidates=CANDIDATES_3)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_local_no_external_calls(self):
        """local mode must NOT call backend.logic.reranker."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        with patch("backend.logic.reranker.rerank_candidates") as mock_vendor:
            svc.rerank(query="볼펜", candidates=CANDIDATES_2)
            mock_vendor.assert_not_called()

    def test_local_error_type_is_none(self):
        """local mode should never produce errors."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
        assert result["error_type"] is None
        assert result["is_fallback"] is False

    def test_local_empty_candidates(self):
        """local mode with empty candidates returns null."""
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        result = svc.rerank(query="볼펜", candidates=[])
        assert result["selected_id"] is None
        assert result["confidence"] == 0.0


# ============================================================================
# 3. vendor sampling — VENDOR_SAMPLE_RATE
# ============================================================================

class TestVendorSampling:
    """VENDOR_SAMPLE_RATE controls how often vendor mode actually calls the LLM."""

    def test_vendor_sample_rate_zero_blocks_vendor(self):
        """VENDOR_SAMPLE_RATE=0 should never call the real reranker."""
        from backend.ml.rerank_service import RerankService
        env = {"VENDOR_SAMPLE_RATE": "0.0"}
        with patch.dict(os.environ, env):
            svc = RerankService(mode="vendor")
            with patch("backend.logic.reranker.rerank_candidates") as mock_vendor:
                result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
                mock_vendor.assert_not_called()
                # Should still return a valid response (local fallback)
                assert result["selected_id"] is not None
                assert result["is_fallback"] is True

    def test_vendor_sample_rate_one_calls_vendor(self):
        """VENDOR_SAMPLE_RATE=1.0 should always call the real reranker."""
        from backend.ml.rerank_service import RerankService
        env = {"VENDOR_SAMPLE_RATE": "1.0"}
        with patch.dict(os.environ, env):
            svc = RerankService(mode="vendor")
            with patch("backend.logic.reranker.rerank_candidates") as mock_vendor:
                mock_vendor.return_value = {
                    "selected_id": "10",
                    "reason": "test",
                    "confidence": 0.9,
                    "latency": 0.1,
                }
                result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
                mock_vendor.assert_called_once()

    def test_vendor_sample_rate_default_is_one(self):
        """Default VENDOR_SAMPLE_RATE should be 1.0 (always call vendor)."""
        from backend.ml.rerank_service import RerankService
        # Remove env var if present
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VENDOR_SAMPLE_RATE", None)
            svc = RerankService(mode="vendor")
            with patch("backend.logic.reranker.rerank_candidates") as mock_vendor:
                mock_vendor.return_value = {
                    "selected_id": "10",
                    "reason": "test",
                    "confidence": 0.9,
                    "latency": 0.1,
                }
                svc.rerank(query="볼펜", candidates=CANDIDATES_2)
                mock_vendor.assert_called_once()


# ============================================================================
# 4. default mode change
# ============================================================================

class TestDefaultMode:
    """Default RERANK_MODE should now be 'simulated'."""

    def test_default_mode_is_simulated(self):
        """When RERANK_MODE env is not set, default should be 'simulated'."""
        from backend.ml.rerank_service import RerankService
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RERANK_MODE", None)
            svc = RerankService()
            assert svc.mode == "simulated"

    def test_all_modes_accepted(self):
        """All four modes should be accepted: mock, vendor, simulated, local."""
        from backend.ml.rerank_service import RerankService
        for mode in ("mock", "vendor", "simulated", "local"):
            svc = RerankService(mode=mode)
            assert svc.mode == mode


# ============================================================================
# 5. error_type standardisation
# ============================================================================

class TestErrorTypeStandard:
    """error_type values must be one of: RATE_LIMIT, TIMEOUT, VENDOR_ERROR, or None."""

    VALID_ERROR_TYPES = {None, "RATE_LIMIT", "TIMEOUT", "VENDOR_ERROR"}

    def test_mock_error_type_standard(self):
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="mock")
        result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
        assert result["error_type"] in self.VALID_ERROR_TYPES

    def test_local_error_type_standard(self):
        from backend.ml.rerank_service import RerankService
        svc = RerankService(mode="local")
        result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
        assert result["error_type"] in self.VALID_ERROR_TYPES

    def test_simulated_error_type_standard(self):
        from backend.ml.rerank_service import RerankService
        env = {
            "SIM_TARGET_LATENCY_MS": "10",
            "SIM_JITTER_MS": "0",
            "SIM_TIMEOUT_RATE": "0.5",
            "SIM_RATE_LIMIT_RATE": "0.5",
            "SIM_VENDOR_ERROR_RATE": "0",
        }
        with patch.dict(os.environ, env):
            svc = RerankService(mode="simulated")
            # Run multiple times to get both error and non-error
            for _ in range(20):
                result = svc.rerank(query="볼펜", candidates=CANDIDATES_2)
                assert result["error_type"] in self.VALID_ERROR_TYPES
