"""
Tests for backend/search/cache.py — Redis cache module

Tests:
  1. cache_get/cache_set round-trip
  2. TTL expiry
  3. Graceful degradation (Redis unavailable)
  4. cache_health
  5. Key isolation (different prefixes)
"""

import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# Test: Graceful degradation when Redis is not available
# ============================================================================

class TestCacheGracefulDegradation:
    """Tests that cache operations are no-ops when Redis is unavailable."""

    def test_cache_get_returns_none_when_unavailable(self):
        """cache_get should return None when Redis is down."""
        import backend.search.cache as cache_mod
        # Force re-check
        cache_mod._redis_available = None
        cache_mod._redis_client = None

        with patch.dict(os.environ, {"REDIS_URL": "redis://nonexistent:9999/0"}):
            cache_mod._redis_available = None
            cache_mod._redis_client = None
            result = cache_mod.cache_get("test", "key")
            assert result is None

    def test_cache_set_returns_false_when_unavailable(self):
        """cache_set should return False when Redis is down."""
        import backend.search.cache as cache_mod
        cache_mod._redis_available = None
        cache_mod._redis_client = None

        with patch.dict(os.environ, {"REDIS_URL": "redis://nonexistent:9999/0"}):
            cache_mod._redis_available = None
            cache_mod._redis_client = None
            result = cache_mod.cache_set("test", "key", {"data": 123})
            assert result is False

    def test_cache_health_unavailable(self):
        """cache_health should report unavailable when Redis is down."""
        import backend.search.cache as cache_mod
        cache_mod._redis_available = None
        cache_mod._redis_client = None

        with patch.dict(os.environ, {"REDIS_URL": "redis://nonexistent:9999/0"}):
            cache_mod._redis_available = None
            cache_mod._redis_client = None
            status = cache_mod.cache_health()
            assert status["connected"] is False


# ============================================================================
# Test: Cache operations with live Redis (skipped if Redis unavailable)
# ============================================================================

def _redis_is_available():
    """Check if Redis is actually reachable."""
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, socket_timeout=2)
        client.ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_is_available(), reason="Redis not available")
class TestCacheLiveRedis:
    """Tests with actual Redis connection. Skipped if Redis is down."""

    def setup_method(self):
        """Reset cache module state before each test."""
        import backend.search.cache as cache_mod
        cache_mod._redis_available = None
        cache_mod._redis_client = None

    def test_set_and_get_roundtrip(self):
        """Set a value and get it back."""
        from backend.search.cache import cache_get, cache_set

        test_value = {"keywords": ["볼펜", "필기구", "펜"], "score": 0.95}
        cache_set("test", "roundtrip_key", test_value, ttl=10)
        result = cache_get("test", "roundtrip_key")

        assert result is not None
        assert result["keywords"] == ["볼펜", "필기구", "펜"]
        assert result["score"] == 0.95

    def test_cache_miss(self):
        """Get a non-existent key returns None."""
        from backend.search.cache import cache_get

        result = cache_get("test", f"nonexistent_{time.time()}")
        assert result is None

    def test_key_isolation(self):
        """Different prefixes produce different keys."""
        from backend.search.cache import cache_get, cache_set

        cache_set("expand", "same_data", ["a", "b"], ttl=10)
        cache_set("search", "same_data", ["x", "y"], ttl=10)

        expand_result = cache_get("expand", "same_data")
        search_result = cache_get("search", "same_data")

        assert expand_result == ["a", "b"]
        assert search_result == ["x", "y"]

    def test_ttl_expiry(self):
        """Value should expire after TTL."""
        from backend.search.cache import cache_get, cache_set

        cache_set("test", "expiry_key", {"temp": True}, ttl=1)
        # Immediately available
        assert cache_get("test", "expiry_key") is not None
        # Wait for TTL
        time.sleep(1.5)
        assert cache_get("test", "expiry_key") is None

    def test_cache_health_connected(self):
        """cache_health should report connected when Redis is up."""
        from backend.search.cache import cache_health

        status = cache_health()
        assert status["connected"] is True
        assert status["status"] == "healthy"
        assert "used_memory_human" in status

    def test_korean_data_roundtrip(self):
        """Korean text should survive serialization."""
        from backend.search.cache import cache_get, cache_set

        korean_data = {
            "primary": "세탁세제",
            "expanded": ["세탁세제", "빨래세제", "세탁용세제"],
        }
        cache_set("test", "korean", korean_data, ttl=10)
        result = cache_get("test", "korean")

        assert result is not None
        assert result["primary"] == "세탁세제"
        assert "빨래세제" in result["expanded"]

    def test_list_type_roundtrip(self):
        """List values (common in keyword expansion) should work."""
        from backend.search.cache import cache_get, cache_set

        keywords = ["건전지", "배터리", "AA건전지"]
        cache_set("expand", "건전지", keywords, ttl=10)
        result = cache_get("expand", "건전지")

        assert result == keywords


# ============================================================================
# Test: Key generation determinism
# ============================================================================

class TestKeyGeneration:
    """Test that cache keys are deterministic."""

    def test_same_input_same_key(self):
        """Same input should produce same key."""
        from backend.search.cache import _make_key

        key1 = _make_key("expand", "볼펜")
        key2 = _make_key("expand", "볼펜")
        assert key1 == key2

    def test_different_input_different_key(self):
        """Different input should produce different key."""
        from backend.search.cache import _make_key

        key1 = _make_key("expand", "볼펜")
        key2 = _make_key("expand", "연필")
        assert key1 != key2

    def test_different_prefix_different_key(self):
        """Same data with different prefix should produce different key."""
        from backend.search.cache import _make_key

        key1 = _make_key("expand", "볼펜")
        key2 = _make_key("search", "볼펜")
        assert key1 != key2

    def test_list_key_order_independent(self):
        """JSON sort_keys ensures list order matters but dict key order doesn't."""
        from backend.search.cache import _make_key

        key1 = _make_key("search", {"a": 1, "b": 2})
        key2 = _make_key("search", {"b": 2, "a": 1})
        assert key1 == key2
