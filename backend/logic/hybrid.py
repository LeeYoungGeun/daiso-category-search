# backend/logic/hybrid.py
"""
Shim module.

기존 코드(backend.logic.integrated_search)가 `from .hybrid import HybridSearchService`
를 쓰는 형태라면, 실제 구현(backend.search.hybrid.HybridSearchService)을 재-export 한다.
"""
from backend.search.hybrid import HybridSearchService  # noqa: F401
