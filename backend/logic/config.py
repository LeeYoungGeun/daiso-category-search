# backend/logic/config.py
"""
Shim module.

integrated_search.py가 `from .config import SearchConfig, RuntimeFlags` 형태를 사용할 때,
실제 구현을 backend.search.config에 두고 여기서 재-export 할 수 있다.

현재 프로젝트 구조에서는 backend.search.config.HybridSearchConfig만 필수이며,
SearchConfig/RuntimeFlags가 필요하면 아래에 확장하면 된다.
"""
from dataclasses import dataclass
from typing import Optional

# 최소 호환: integrated_search에서 타입 힌트로만 쓰는 경우를 대비
@dataclass
class RuntimeFlags:
    safe_mode: bool = False
    disable_hybrid: bool = False
    force_sqlite: bool = False

@dataclass
class SearchConfig:
    # 필요 시 확장
    search_mode: str = "auto"
    elastic_url: Optional[str] = None
    qdrant_url: Optional[str] = None
