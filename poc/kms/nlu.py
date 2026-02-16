"""poc/kms/nlu.py

목표
- backend/logic/integrated_search.py 가 아래 심볼을 import 할 수 있어야 함:
    - analyze_text (async)
    - expand_search_keywords (async)
- SAFE_MODE=1 이거나 API KEY 미설정이면 외부 벤더 호출을 절대 하지 않고,
  로컬/휴리스틱만으로 동작(빈값이어도 형태는 유지)

주의
- 이 파일 안에서 `from poc.kms.nlu import ...` 같은 자기 자신 import를 하면
  "partially initialized module" 순환 import가 터집니다. 절대 금지.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


SAFE_MODE: bool = _env_bool("SAFE_MODE", False)

# (있으면 쓰되, SAFE_MODE면 호출 자체를 안 함)
GEMINI_MODEL: str = (os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_MODEL_NAME") or "gemini-2.0-flash").strip()
GOOGLE_API_KEY: str = (os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_API_KEY: str = (os.getenv("GEMINI_API_KEY") or "").strip()

_client = None


def _get_api_key() -> str:
    # 프로젝트에서 GOOGLE_API_KEY 우선 사용 흐름을 유지
    return GOOGLE_API_KEY or GEMINI_API_KEY


def get_client():
    """google-genai Client를 반환.

    - SAFE_MODE=1 이거나 API KEY 미설정이면 None 반환(벤더 호출 차단).
    """
    global _client
    if SAFE_MODE:
        return None

    api_key = _get_api_key()
    if not api_key:
        return None

    if _client is None:
        try:
            from google import genai  # type: ignore
        except Exception:
            return None
        _client = genai.Client(api_key=api_key)

    return _client


# ---- 결과 타입 (integrated_search가 기대하는 형태 유지) ----

@dataclass
class Intent:
    value: str


class Slots:
    def __init__(
        self,
        item: Optional[str] = None,
        query_rewrite: Optional[str] = None,
        attrs: Optional[Dict[str, Any]] = None,
    ):
        self.item = item
        self.query_rewrite = query_rewrite
        self.attrs = attrs or {}

    def model_dump(self) -> Dict[str, Any]:
        return {"item": self.item, "query_rewrite": self.query_rewrite, "attrs": self.attrs}


class NLUResult:
    def __init__(
        self,
        intent: str,
        slots: Slots,
        needs_clarification: bool = False,
        token_usage: Optional[Dict[str, Any]] = None,
    ):
        self.intent = Intent(intent)
        self.slots = slots
        self.needs_clarification = needs_clarification
        self.token_usage = token_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# ---- 로컬 휴리스틱 ----

def _normalize(text: str) -> str:
    return (text or "").strip()


def _guess_intent(query: str) -> str:
    q = _normalize(query)
    if not q:
        return "UNSUPPORTED"

    # 프로젝트 컨벤션:
    # - "상품 위치" 류 질문은 PRODUCT_LOCATION
    # - 나머지는 PRODUCT_SEARCH
    if any(k in q for k in ["어디", "위치", "코너", "몇 번", "찾아", "어딨어", "있어?", "있나요"]):
        return "PRODUCT_LOCATION"

    return "PRODUCT_SEARCH"


def _extract_item(query: str) -> Optional[str]:
    q = _normalize(query)
    if not q:
        return None

    # 아주 단순한 조사/어미 제거(로컬 폴백용)
    q2 = re.sub(r"(어디(에|야)?|있(어|나요|\?)?|찾(아|는데).*|코너|몇\s*번|주세요)$", "", q).strip()
    return q2 or None


async def analyze_text(query: str, history: Optional[List[Dict[str, str]]] = None) -> NLUResult:
    """NLU 분석.

    integrated_search.py가 아래 둘 중 어떤 형태로 호출해도 동작해야 함:
    - await analyze_text(query, history=history)
    - await analyze_text(query)
    """
    start = time.time()

    # SAFE_MODE 또는 클라이언트 미구성 시 로컬 추정
    if SAFE_MODE or get_client() is None:
        intent = _guess_intent(query)
        item = _extract_item(query)
        slots = Slots(item=item, query_rewrite=query, attrs={})
        return NLUResult(
            intent=intent,
            slots=slots,
            needs_clarification=False,
            token_usage={
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_seconds": time.time() - start,
            },
        )

    # (비 SAFE_MODE) 여기서 벤더 NLU를 연결할 수 있음.
    # 지금은 비용/안정성 우선으로 로컬과 동일하게 처리.
    intent = _guess_intent(query)
    item = _extract_item(query)
    slots = Slots(item=item, query_rewrite=query, attrs={})
    return NLUResult(
        intent=intent,
        slots=slots,
        needs_clarification=False,
        token_usage={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": time.time() - start,
        },
    )


async def expand_search_keywords(
    primary_keyword: str,
    return_usage: bool = False,
) -> Tuple[List[str], Dict[str, Any]]:
    """키워드 확장.

    규칙
    - SAFE_MODE=1 이면 무조건 외부호출 없이 빈 확장(또는 로컬 규칙)만 반환
    - primary_keyword가 비어있으면 [] 반환
    - return_usage 파라미터는 하위 호환을 위해 유지 (항상 (list, usage) 형태로 반환)
    """
    start = time.time()
    usage: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "latency_seconds": 0.0}

    kw = _normalize(primary_keyword)
    if not kw:
        usage["latency_seconds"] = time.time() - start
        return ([], usage) if return_usage else ([], usage)

    # SAFE_MODE 또는 클라이언트 미구성: 로컬 규칙만
    if SAFE_MODE or get_client() is None:
        expansions: List[str] = []
        # 로컬 규칙 예시(필요 시 확장)
        if kw in ("건전지", "배터리"):
            expansions = ["배터리", "건전지", "AA", "AAA"]
        usage["latency_seconds"] = time.time() - start
        return (expansions, usage) if return_usage else (expansions, usage)

    # (비 SAFE_MODE) 여기서 벤더 호출 기반 확장을 붙일 수 있음.
    # 지금은 안정성/비용 이유로 로컬만 반환.
    expansions: List[str] = []
    usage["latency_seconds"] = time.time() - start
    return (expansions, usage) if return_usage else (expansions, usage)
