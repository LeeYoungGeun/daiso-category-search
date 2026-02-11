"""
ML Rerank Layer Tests — TDD Red Phase

Tests for:
1. RerankService with RERANK_MODE=mock|vendor switch
2. Response schema: latency_ms, is_fallback, error_type
3. /ml/rerank HTTP endpoint
4. Edge cases: empty candidates, timeout, error handling
"""

import pytest
import sys
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# 1. RerankService — mock mode
# ============================================================================

class TestRerankServiceMockMode:
    """RerankService in mock mode should return deterministic results instantly."""

    def test_mock_mode_returns_valid_response(self):
        """Mock mode should return a valid rerank response with all required fields."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(
            query="튀김 건질 때 쓰는 거",
            candidates=[
                {"id": "1", "name": "스텐 채반", "desc": "튀김용"},
                {"id": "2", "name": "세탁망", "desc": "세탁기용"},
            ],
        )
        assert "selected_id" in result
        assert "reason" in result
        assert "confidence" in result
        assert "latency_ms" in result
        assert "is_fallback" in result
        assert "error_type" in result

    def test_mock_mode_latency_is_low(self):
        """Mock mode latency should be < 50ms (no real LLM call)."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(
            query="볼펜",
            candidates=[{"id": "1", "name": "파란 볼펜", "desc": "필기구"}],
        )
        assert result["latency_ms"] < 50

    def test_mock_mode_is_not_fallback(self):
        """Mock mode normal response should have is_fallback=False."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(
            query="볼펜",
            candidates=[{"id": "1", "name": "볼펜", "desc": "필기구"}],
        )
        assert result["is_fallback"] is False

    def test_mock_mode_error_type_is_none(self):
        """Mock mode normal response should have error_type=None."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(
            query="볼펜",
            candidates=[{"id": "1", "name": "볼펜", "desc": "필기구"}],
        )
        assert result["error_type"] is None

    def test_mock_mode_selects_first_candidate(self):
        """Mock mode should deterministically select the first candidate."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(
            query="아무거나",
            candidates=[
                {"id": "A", "name": "상품A", "desc": "설명A"},
                {"id": "B", "name": "상품B", "desc": "설명B"},
            ],
        )
        assert result["selected_id"] == "A"


# ============================================================================
# 2. RerankService — vendor mode
# ============================================================================

class TestRerankServiceVendorMode:
    """RerankService in vendor mode should delegate to the real reranker."""

    def test_vendor_mode_delegates_to_reranker(self):
        """Vendor mode should call the existing rerank_candidates function."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="vendor")
        with patch("backend.logic.reranker.rerank_candidates") as mock_rerank:
            mock_rerank.return_value = {
                "selected_id": "1",
                "reason": "테스트",
                "confidence": 0.9,
                "latency": 0.5,
            }
            result = svc.rerank(
                query="볼펜",
                candidates=[{"id": "1", "name": "볼펜", "desc": "필기구"}],
            )
            mock_rerank.assert_called_once()
            assert result["selected_id"] == "1"
            assert result["latency_ms"] >= 0
            assert result["is_fallback"] is False
            assert result["error_type"] is None

    def test_vendor_mode_fallback_on_error(self):
        """Vendor mode should fallback gracefully when reranker raises."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="vendor")
        with patch("backend.logic.reranker.rerank_candidates") as mock_rerank:
            mock_rerank.side_effect = Exception("LLM timeout")
            result = svc.rerank(
                query="볼펜",
                candidates=[{"id": "1", "name": "볼펜", "desc": "필기구"}],
            )
            assert result["is_fallback"] is True
            assert result["error_type"] == "VENDOR_ERROR"
            assert result["selected_id"] is not None  # fallback still picks something


# ============================================================================
# 3. RerankService — edge cases
# ============================================================================

class TestRerankServiceEdgeCases:
    """Edge case handling for RerankService."""

    def test_empty_candidates(self):
        """Empty candidates should return null selected_id, confidence 0."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(query="볼펜", candidates=[])
        assert result["selected_id"] is None
        assert result["confidence"] == 0.0
        assert result["latency_ms"] >= 0

    def test_single_candidate(self):
        """Single candidate should be selected with high confidence."""
        from backend.ml.rerank_service import RerankService

        svc = RerankService(mode="mock")
        result = svc.rerank(
            query="볼펜",
            candidates=[{"id": "1", "name": "볼펜", "desc": "필기구"}],
        )
        assert result["selected_id"] == "1"
        assert result["confidence"] > 0.5

    def test_mode_from_env_variable(self):
        """RerankService should read RERANK_MODE from env if not passed."""
        from backend.ml.rerank_service import RerankService

        with patch.dict(os.environ, {"RERANK_MODE": "mock"}):
            svc = RerankService()
            assert svc.mode == "mock"

    def test_default_mode_is_simulated(self):
        """Default mode should be 'simulated' when env is not set."""
        from backend.ml.rerank_service import RerankService

        with patch.dict(os.environ, {}, clear=True):
            # Remove RERANK_MODE if present
            os.environ.pop("RERANK_MODE", None)
            svc = RerankService()
            assert svc.mode == "simulated"

    def test_invalid_mode_raises(self):
        """Invalid mode should raise ValueError."""
        from backend.ml.rerank_service import RerankService

        with pytest.raises(ValueError, match="mode"):
            RerankService(mode="invalid_mode")


# ============================================================================
# 4. /ml/rerank API endpoint tests (using FastAPI TestClient)
# ============================================================================

class TestMlRerankEndpoint:
    """Test the /ml/rerank HTTP endpoint (async, httpx 0.28+)."""

    @pytest.fixture
    def client(self):
        """Create an async httpx client with RERANK_MODE=mock."""
        with patch.dict(os.environ, {"RERANK_MODE": "mock"}):
            import httpx
            from backend.dev_server import app

            transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
            return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    @pytest.mark.asyncio
    async def test_rerank_endpoint_exists(self, client):
        """POST /ml/rerank should return 200, not 404."""
        async with client:
            resp = await client.post("/ml/rerank", json={
                "query": "볼펜",
                "candidates": [{"id": "1", "name": "볼펜", "desc": "필기구"}],
            })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rerank_endpoint_response_schema(self, client):
        """Response should contain all required fields."""
        async with client:
            resp = await client.post("/ml/rerank", json={
                "query": "튀김 건질 때 쓰는 거",
                "candidates": [
                    {"id": "1", "name": "스텐 채반", "desc": "튀김용"},
                    {"id": "2", "name": "세탁망", "desc": "세탁기용"},
                ],
            })
        data = resp.json()
        assert "selected_id" in data
        assert "reason" in data
        assert "confidence" in data
        assert "latency_ms" in data
        assert "is_fallback" in data
        assert "error_type" in data

    @pytest.mark.asyncio
    async def test_rerank_endpoint_empty_candidates(self, client):
        """Empty candidates should return 200 with null selected_id."""
        async with client:
            resp = await client.post("/ml/rerank", json={
                "query": "볼펜",
                "candidates": [],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_id"] is None

    @pytest.mark.asyncio
    async def test_rerank_endpoint_missing_query(self, client):
        """Missing query should return 422 validation error."""
        async with client:
            resp = await client.post("/ml/rerank", json={
                "candidates": [{"id": "1", "name": "볼펜", "desc": "필기구"}],
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rerank_endpoint_latency_header(self, client):
        """Response should include X-Rerank-Latency-Ms header."""
        async with client:
            resp = await client.post("/ml/rerank", json={
                "query": "볼펜",
                "candidates": [{"id": "1", "name": "볼펜", "desc": "필기구"}],
            })
        assert "x-rerank-latency-ms" in resp.headers

    @pytest.mark.asyncio
    async def test_rerank_endpoint_returns_json(self, client):
        """Response content-type should be application/json."""
        async with client:
            resp = await client.post("/ml/rerank", json={
                "query": "볼펜",
                "candidates": [{"id": "1", "name": "볼펜", "desc": "필기구"}],
            })
        assert "application/json" in resp.headers.get("content-type", "")
