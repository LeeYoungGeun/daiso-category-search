"""
Redis Cache Service for Search Pipeline

Provides caching for:
  1. Keyword expansion results (Gemini API call reduction)
  2. Hybrid search results (ES/Qdrant call reduction)

Graceful degradation: if Redis is unavailable, all operations are no-ops.
"""

import json
import hashlib
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# [PATCH] Cache key 직렬화 강화:
# - dict key order 뿐 아니라 list/tuple/set 등 비정형 타입도 안정적으로 직렬화
# - json.dumps 실패 시 repr 기반 fallback로 key 생성이 깨지지 않도록 처리
def _normalize_key_data(data: Any) -> Any:
    """Normalize key data into JSON-serializable deterministic structure."""
    if data is None:
        return None
    # Primitive JSON types
    if isinstance(data, (str, int, float, bool)):
        return data
    # Bytes -> decode best-effort
    if isinstance(data, (bytes, bytearray)):
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return str(data)
    # Dict -> sort keys via json.dumps(sort_keys=True) later
    if isinstance(data, dict):
        return {str(k): _normalize_key_data(v) for k, v in data.items()}
    # List/Tuple -> preserve order (order can be semantically meaningful)
    if isinstance(data, (list, tuple)):
        return [_normalize_key_data(x) for x in data]
    # Set -> sort to be deterministic
    if isinstance(data, set):
        return sorted(_normalize_key_data(x) for x in data)
    # Fallback: stringify
    return str(data)

_redis_client = None
_redis_available = None  # tri-state: None=not checked, True/False

DEFAULT_TTL = int(os.getenv("REDIS_CACHE_TTL", "300"))  # 5 min


def _get_redis():
    """Lazy-init Redis client. Returns None if unavailable."""
    global _redis_client, _redis_available

    if _redis_available is False:
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        import redis as redis_lib
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis_lib.from_url(url, decode_responses=True, socket_timeout=2)
        client.ping()
        _redis_client = client
        _redis_available = True
        logger.info(f"✅ Redis cache connected: {url}")
        return client
    except ImportError:
        logger.warning("⚠️ redis-py not installed — cache disabled")
        _redis_available = False
        return None
    except Exception as e:
        logger.warning(f"⚠️ Redis not reachable — cache disabled: {e}")
        _redis_available = False
        return None


def _make_key(prefix: str, data: Any) -> str:
    """Generate deterministic Redis cache key."""
    # NOTE: 기존 키 포맷(daiso:{prefix}:{16-hex})은 유지하되,
    #       key_data 직렬화를 더 안전하게 만듭니다.  # [PATCH]
    norm = _normalize_key_data(data)
    try:
        raw = json.dumps(norm, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        raw = repr(norm)  # [PATCH] serialization fail-safe

    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"daiso:{prefix}:{h}"


# ─── Public API ──────────────────────────────────────────────────────────────


def cache_get(prefix: str, key_data: Any) -> Optional[Any]:
    """
    Get cached value. Returns None on miss or if Redis unavailable.
    """
    client = _get_redis()
    if client is None:
        return None

    key = _make_key(prefix, key_data)
    try:
        raw = client.get(key)
        if raw is not None:
            logger.debug(f"Cache HIT: {key}")
            return json.loads(raw)
        logger.debug(f"Cache MISS: {key}")
        return None
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
        return None


def cache_set(prefix: str, key_data: Any, value: Any, ttl: int = DEFAULT_TTL) -> bool:
    """
    Set cached value with TTL. Returns True on success.
    """
    client = _get_redis()
    if client is None:
        return False

    key = _make_key(prefix, key_data)
    try:
        raw = json.dumps(value, ensure_ascii=False)
        client.setex(key, ttl, raw)
        logger.debug(f"Cache SET: {key} (ttl={ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"Cache set error: {e}")
        return False


def cache_health() -> dict:
    """Check Redis health. Returns status dict."""
    client = _get_redis()
    if client is None:
        return {"status": "unavailable", "connected": False}

    try:
        info = client.info("memory")
        return {
            "status": "healthy",
            "connected": True,
            "used_memory_human": info.get("used_memory_human", "?"),
            "maxmemory_human": info.get("maxmemory_human", "?"),
        }
    except Exception as e:
        return {"status": "error", "connected": False, "error": str(e)}
