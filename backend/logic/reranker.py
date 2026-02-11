"""
M2: Reranker Module

Wraps the PoC reranking logic (poc/kdg/) with confidence scoring
and proper error handling for the integrated pipeline.
"""

import os
import json
import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# Reranker Configuration
# ============================================================================

MODEL_NAME = "gemini-1.5-flash"

RERANK_SYSTEM_PROMPT = """
You are an expert AI Search Agent for Daiso (a variety store).
Your goal is to select the BEST matching product from a list of candidates based on a user's query.

[Principles]
1.  **Intent First**: Understand the user's core need. (e.g., "net for frying" -> Kitchen tool, NOT laundry net).
2.  **Context Aware**: If the query is broad (e.g., "detergent"), prefer the most standard/popular item unless context implies otherwise.
3.  **Strict Negative Filtering**: If a user says "NO plastic", reject plastic items.
4.  **Null Safety**: If NO candidate matches the intent, return `null`. Do NOT force a selection.
5.  **Confidence**: Rate your confidence in the selection from 0.0 (no match) to 1.0 (perfect match).

[Output Format]
{
    "selected_id": "string or null",
    "reason": "string (Korean)",
    "confidence": 0.0 to 1.0
}

[Few-Shot Examples]

**Example 1: Specific Function**
User Query: "튀김 건질 때 쓰는 거"
Candidates:
- ID A1: "세탁망 (원형)" - 세탁기용 망
- ID B2: "스텐 채반 (손잡이형)" - 튀김/면 요리용
- ID C3: "튀김가루 1kg" - 식재료
Output: {"selected_id": "B2", "reason": "사용자가 조리 도구를 찾고 있으며, 스텐 채반이 튀김 건지기에 가장 적합합니다.", "confidence": 0.95}

**Example 2: No Match**
User Query: "아이폰 충전기"
Candidates:
- ID D1: "건전지 AA 2개입"
- ID D2: "갤럭시 C타입 케이블" - 삼성 호환
Output: {"selected_id": null, "reason": "후보군에 아이폰 전용 충전기나 케이블이 없습니다.", "confidence": 0.0}

**Example 3: Visual Description**
User Query: "그.. 뽁뽁이.. 겨울에 창문에 붙이는거"
Candidates:
- ID E1: "단열 시트 (에어캡)"
- ID E2: "장난감 뽁뽁이"
Output: {"selected_id": "E1", "reason": "'뽁뽁이'는 에어캡의 은어이며, 겨울철 창문에 붙인다는 문맥으로 보아 단열 시트가 정답입니다.", "confidence": 0.9}
"""


# ============================================================================
# Client Management
# ============================================================================

_client = None


def _get_client():
    """Lazy-init Gemini client"""
    global _client
    if _client is None:
        try:
            from google import genai
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("GEMINI_API_KEY not set, reranker will use fallback")
                return None
            _client = genai.Client(api_key=api_key)
        except ImportError:
            logger.warning("google-genai not installed, reranker will use fallback")
            return None
    return _client


# ============================================================================
# Core Reranking Function
# ============================================================================

def rerank_candidates(
    user_query: str,
    candidates: List[Dict[str, Any]],
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    Rerank search candidates using Gemini LLM with confidence scoring.

    Args:
        user_query: The user's search query
        candidates: List of candidate dicts with 'id', 'name', 'desc' fields
        timeout: Maximum time for LLM call in seconds

    Returns:
        Dict with 'selected_id', 'reason', 'confidence', 'latency'
    """
    # Handle empty candidates
    if not candidates:
        return {
            "selected_id": None,
            "reason": "후보 상품이 없습니다.",
            "confidence": 0.0,
            "latency": 0,
        }

    # Try LLM reranking
    client = _get_client()
    if client is None:
        return _fallback_rerank(user_query, candidates)

    try:
        return _llm_rerank(client, user_query, candidates, timeout)
    except Exception as e:
        logger.error(f"LLM rerank failed: {e}")
        return _fallback_rerank(user_query, candidates)


def _llm_rerank(
    client,
    user_query: str,
    candidates: List[Dict[str, Any]],
    timeout: float,
) -> Dict[str, Any]:
    """Rerank using Gemini LLM"""
    from google.genai import types

    # Build candidate text
    candidate_text = ""
    for c in candidates:
        name = c.get("name", "Unknown")
        desc = c.get("desc", "") or c.get("searchable_desc", "") or "No description"
        desc = desc[:100]  # Truncate for token efficiency
        candidate_text += f"- ID {c['id']}: {name} (Desc: {desc})\n"

    prompt = f"""
    {RERANK_SYSTEM_PROMPT}

    [Current Task]
    User Query: "{user_query}"

    Candidates:
    {candidate_text}

    Output JSON:
    {{
        "selected_id": "string or null",
        "reason": "string (Korean)",
        "confidence": 0.0 to 1.0
    }}
    """

    start_time = time.time()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    latency = time.time() - start_time

    response_text = response.text or "{}"
    result = json.loads(response_text)

    # Ensure confidence is present and valid
    confidence = result.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    return {
        "selected_id": result.get("selected_id"),
        "reason": result.get("reason", ""),
        "confidence": confidence,
        "latency": latency,
    }


def _fallback_rerank(
    user_query: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Simple fallback reranking when LLM is unavailable.
    Uses basic keyword matching to score candidates.
    """
    if not candidates:
        return {
            "selected_id": None,
            "reason": "후보 상품이 없습니다.",
            "confidence": 0.0,
            "latency": 0,
        }

    query_lower = user_query.lower()
    query_tokens = set(query_lower.split())

    best_score = 0
    best_candidate = candidates[0]

    for c in candidates:
        name = c.get("name", "").lower()
        desc = (c.get("desc", "") or "").lower()
        text = f"{name} {desc}"

        # Simple token overlap scoring
        score = 0
        for token in query_tokens:
            if token in text:
                score += 1

        # Exact name match bonus
        if query_lower in name:
            score += 3

        if score > best_score:
            best_score = score
            best_candidate = c

    # Calculate confidence based on match quality
    max_possible = len(query_tokens) + 3  # max token matches + exact match bonus
    confidence = min(1.0, best_score / max(max_possible, 1)) if best_score > 0 else 0.3

    return {
        "selected_id": str(best_candidate["id"]),
        "reason": f"키워드 매칭 기반 선택: {best_candidate.get('name', '')}",
        "confidence": confidence,
        "latency": 0,
    }
