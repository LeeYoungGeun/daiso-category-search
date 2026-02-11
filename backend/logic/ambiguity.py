"""
M2: Ambiguity Detection & Clarification Module

Detects ambiguous queries, generates follow-up questions,
and manages the 2-strike fallback mechanism.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
from collections import defaultdict

from backend.logic.schemas import AmbiguityType


# ============================================================================
# Configuration Thresholds
# ============================================================================

# If search results span >= this many distinct categories, query is broad
CATEGORY_SPREAD_THRESHOLD = 3

# If candidates count exceeds this, likely too broad
HIGH_CANDIDATE_THRESHOLD = 8

# Maximum clarification attempts before fallback
MAX_CLARIFICATION_STRIKES = 2


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class AmbiguityResult:
    """Result of ambiguity detection"""
    ambiguity_type: AmbiguityType
    is_ambiguous: bool
    confidence: float  # 0.0 = very ambiguous, 1.0 = very clear
    reason: str


# ============================================================================
# Core Detection Functions
# ============================================================================

def detect_ambiguity(
    item: Optional[str],
    attrs: List[str],
    candidates_count: int,
    category_spread: int,
    nlu_needs_clarification: bool,
) -> AmbiguityResult:
    """
    Detect the type and severity of ambiguity in a user query.

    Args:
        item: Extracted product name (None if not identified)
        attrs: Extracted attributes
        candidates_count: Number of search results found
        category_spread: Number of distinct categories in results
        nlu_needs_clarification: Whether NLU flagged the query as needing clarification

    Returns:
        AmbiguityResult with type, is_ambiguous flag, confidence, and reason
    """
    # Case 1: No results at all
    if candidates_count == 0:
        return AmbiguityResult(
            ambiguity_type=AmbiguityType.NO_RESULTS,
            is_ambiguous=True,
            confidence=0.2,
            reason="검색 결과가 없습니다. 다른 키워드로 시도해 주세요.",
        )

    # Case 2: No item extracted + NLU flagged clarification → vague description
    if item is None and nlu_needs_clarification:
        return AmbiguityResult(
            ambiguity_type=AmbiguityType.VAGUE_DESCRIPTION,
            is_ambiguous=True,
            confidence=0.3,
            reason="구체적인 상품명이 파악되지 않았습니다.",
        )

    # Case 3: High category spread → broad category or multi-intent
    if category_spread >= CATEGORY_SPREAD_THRESHOLD:
        # If item exists with attributes, it's multi-intent (specific but ambiguous)
        # If item exists without attributes, it's a broad category term
        if item and attrs and candidates_count > HIGH_CANDIDATE_THRESHOLD:
            return AmbiguityResult(
                ambiguity_type=AmbiguityType.MULTI_INTENT,
                is_ambiguous=True,
                confidence=0.4,
                reason=f"'{item}' 검색 결과가 {category_spread}개 카테고리에 걸쳐 있습니다.",
            )
        return AmbiguityResult(
            ambiguity_type=AmbiguityType.BROAD_CATEGORY,
            is_ambiguous=True,
            confidence=0.35,
            reason=f"검색 결과가 {category_spread}개 카테고리에 걸쳐 있어 범위가 넓습니다.",
        )

    # Case 4: Too many results even within few categories
    if candidates_count > HIGH_CANDIDATE_THRESHOLD and not attrs:
        return AmbiguityResult(
            ambiguity_type=AmbiguityType.BROAD_CATEGORY,
            is_ambiguous=True,
            confidence=0.5,
            reason=f"검색 결과가 {candidates_count}개로 많습니다. 더 구체적인 키워드가 필요합니다.",
        )

    # Case 5: NLU flagged but we have some results
    if nlu_needs_clarification and candidates_count > 0:
        return AmbiguityResult(
            ambiguity_type=AmbiguityType.VAGUE_DESCRIPTION,
            is_ambiguous=True,
            confidence=0.5,
            reason="NLU가 추가 확인이 필요하다고 판단했습니다.",
        )

    # Case 6: Clear query — good item, few results, narrow categories
    confidence = 1.0
    if not attrs:
        confidence = 0.8  # Slightly less confident without attributes
    if candidates_count <= 3 and category_spread <= 1:
        confidence = min(confidence + 0.1, 1.0)

    return AmbiguityResult(
        ambiguity_type=AmbiguityType.NONE,
        is_ambiguous=False,
        confidence=confidence,
        reason="명확한 검색 쿼리입니다.",
    )


# ============================================================================
# Category Spread Calculation
# ============================================================================

def calculate_category_spread(candidates: List[Dict]) -> int:
    """
    Calculate how many distinct categories the search results span.

    Args:
        candidates: List of search result dicts with 'category' or 'category_major' field

    Returns:
        Number of distinct categories
    """
    if not candidates:
        return 0

    categories = set()
    for c in candidates:
        cat = c.get("category") or c.get("category_major") or "기타"
        categories.add(cat)

    return len(categories)


# ============================================================================
# Clarification Options Generation
# ============================================================================

def generate_clarification_options(
    candidates: List[Dict],
    item: Optional[str] = None,
) -> List[str]:
    """
    Generate drill-down options from search result categories.

    Groups candidates by category and returns human-readable options.

    Args:
        candidates: Search result dicts with 'name' and 'category' fields
        item: The original search item (for context)

    Returns:
        List of option strings (Korean)
    """
    if not candidates:
        return []

    # Group by category
    grouped = defaultdict(list)
    for c in candidates:
        cat = c.get("category") or c.get("category_major") or "기타"
        grouped[cat].append(c.get("name", ""))

    # Build options from top categories
    options = []
    sorted_groups = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

    for cat, names in sorted_groups[:4]:  # Max 4 options
        # Pick representative product names
        sample_names = names[:2]
        sample_str = ", ".join(sample_names)
        option = f"{cat} ({sample_str})"
        options.append(option)

    return options


def build_clarification_question(
    item: Optional[str],
    options: List[str],
) -> str:
    """
    Build a polite Korean clarification question with options.

    Args:
        item: The search item (may be None)
        options: List of option strings

    Returns:
        Formatted question string in Korean
    """
    if not options:
        return "어떤 상품을 찾으시나요? 좀 더 구체적으로 말씀해 주세요."

    item_str = f"'{item}'" if item else "찾으시는 상품"

    if len(options) == 1:
        return f"{item_str} 관련으로 {options[0]}을(를) 찾으시나요?"

    options_text = "\n".join(f"  {i+1}. {opt}" for i, opt in enumerate(options))
    return f"{item_str}에 대해 여러 종류가 있습니다. 어떤 것을 찾으시나요?\n{options_text}"


# ============================================================================
# 2-Strike Fallback
# ============================================================================

def should_fallback(clarification_count: int) -> bool:
    """
    Determine if we should stop asking and fallback to best-effort results.

    After MAX_CLARIFICATION_STRIKES (2) attempts, stop asking and show results.

    Args:
        clarification_count: Number of clarification attempts already made

    Returns:
        True if should fallback, False if can still ask
    """
    return clarification_count >= MAX_CLARIFICATION_STRIKES
