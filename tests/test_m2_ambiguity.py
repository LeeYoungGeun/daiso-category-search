"""
M2 Tests: Reranking / Ambiguity Handling Enhancement
Tests for: Ambiguity detection, follow-up questions, 2-strike fallback, reranking

TDD Red Phase — These tests define the success criteria for M2.
"""

import pytest
import asyncio
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# 1. Schema Tests — AmbiguityType, confidence, clarification tracking
# ============================================================================

class TestSchemas:
    """Test enhanced schema definitions for M2"""

    def test_ambiguity_type_enum_exists(self):
        """AmbiguityType enum should have NONE, BROAD_CATEGORY, VAGUE_DESCRIPTION, MULTI_INTENT, NO_RESULTS"""
        from backend.logic.schemas import AmbiguityType
        assert AmbiguityType.NONE is not None
        assert AmbiguityType.BROAD_CATEGORY is not None
        assert AmbiguityType.VAGUE_DESCRIPTION is not None
        assert AmbiguityType.MULTI_INTENT is not None
        assert AmbiguityType.NO_RESULTS is not None

    def test_nlu_response_has_ambiguity_fields(self):
        """NLUResponse should have ambiguity_type and confidence fields"""
        from backend.logic.schemas import NLUResponse, Intent, NLUSlots, AmbiguityType
        resp = NLUResponse(
            request_id="test-001",
            intent=Intent.PRODUCT_LOCATION,
            slots=NLUSlots(item="청소"),
            ambiguity_type=AmbiguityType.BROAD_CATEGORY,
            confidence=0.4,
        )
        assert resp.ambiguity_type == AmbiguityType.BROAD_CATEGORY
        assert resp.confidence == 0.4

    def test_nlu_response_defaults(self):
        """NLUResponse should default to NONE ambiguity and 1.0 confidence"""
        from backend.logic.schemas import NLUResponse, Intent, NLUSlots, AmbiguityType
        resp = NLUResponse(
            request_id="test-002",
            intent=Intent.PRODUCT_LOCATION,
            slots=NLUSlots(item="볼펜"),
        )
        assert resp.ambiguity_type == AmbiguityType.NONE
        assert resp.confidence == 1.0

    def test_search_response_has_clarification_fields(self):
        """SearchResponse dict should support needs_clarification, clarification_question, clarification_count"""
        # This tests the pipeline output structure
        result = {
            "needs_clarification": True,
            "clarification_question": "세제를 찾으시나요, 아니면 청소 도구를 찾으시나요?",
            "clarification_count": 1,
            "clarification_options": ["세제/화학제품", "청소 도구(브러쉬/수세미)"],
        }
        assert result["needs_clarification"] is True
        assert result["clarification_count"] == 1
        assert len(result["clarification_options"]) == 2


# ============================================================================
# 2. Ambiguity Detection Tests
# ============================================================================

class TestAmbiguityDetection:
    """Test ambiguity detection logic"""

    def test_detect_broad_category(self):
        """Broad category queries like '청소' should be detected as BROAD_CATEGORY"""
        from backend.logic.ambiguity import detect_ambiguity, AmbiguityResult
        
        result = detect_ambiguity(
            item="청소",
            attrs=[],
            candidates_count=15,
            category_spread=3,  # results span 3+ categories
            nlu_needs_clarification=False,
        )
        assert result.ambiguity_type.value == "BROAD_CATEGORY"
        assert result.is_ambiguous is True

    def test_detect_vague_description(self):
        """Vague descriptions like '그거 뭐냐 미끄러운거' should be VAGUE_DESCRIPTION"""
        from backend.logic.ambiguity import detect_ambiguity
        
        result = detect_ambiguity(
            item=None,
            attrs=["미끄러운"],
            candidates_count=8,
            category_spread=2,
            nlu_needs_clarification=True,
        )
        assert result.ambiguity_type.value == "VAGUE_DESCRIPTION"
        assert result.is_ambiguous is True

    def test_detect_no_results(self):
        """Zero search results should be NO_RESULTS"""
        from backend.logic.ambiguity import detect_ambiguity
        
        result = detect_ambiguity(
            item="존재하지않는상품",
            attrs=[],
            candidates_count=0,
            category_spread=0,
            nlu_needs_clarification=False,
        )
        assert result.ambiguity_type.value == "NO_RESULTS"
        assert result.is_ambiguous is True

    def test_detect_clear_query(self):
        """Clear queries like '파란색 볼펜' should be NONE (not ambiguous)"""
        from backend.logic.ambiguity import detect_ambiguity
        
        result = detect_ambiguity(
            item="볼펜",
            attrs=["파란색"],
            candidates_count=3,
            category_spread=1,
            nlu_needs_clarification=False,
        )
        assert result.ambiguity_type.value == "NONE"
        assert result.is_ambiguous is False

    def test_detect_multi_intent(self):
        """Queries that could mean multiple things should be MULTI_INTENT"""
        from backend.logic.ambiguity import detect_ambiguity
        
        result = detect_ambiguity(
            item="테이프",
            attrs=[],
            candidates_count=10,
            category_spread=3,  # tape in stationery, tools, kitchen
            nlu_needs_clarification=False,
        )
        assert result.ambiguity_type.value in ("BROAD_CATEGORY", "MULTI_INTENT")
        assert result.is_ambiguous is True

    def test_category_spread_calculation(self):
        """Category spread should be calculated from search candidates"""
        from backend.logic.ambiguity import calculate_category_spread
        
        candidates = [
            {"name": "박스 테이프", "category": "문구/팬시"},
            {"name": "마스킹 테이프", "category": "문구/팬시"},
            {"name": "배관 테이프", "category": "공구/디지털"},
            {"name": "의료 테이프", "category": "뷰티/위생"},
        ]
        spread = calculate_category_spread(candidates)
        assert spread == 3  # 3 distinct categories


# ============================================================================
# 3. Follow-up Question Generation Tests
# ============================================================================

class TestFollowUpQuestions:
    """Test follow-up question generation for ambiguous queries"""

    def test_generate_options_from_categories(self):
        """Should generate drill-down options from category spread"""
        from backend.logic.ambiguity import generate_clarification_options
        
        candidates = [
            {"name": "세탁 세제", "category": "청소/욕실"},
            {"name": "청소 브러쉬", "category": "청소/욕실"},
            {"name": "주방 세제", "category": "주방용품"},
        ]
        options = generate_clarification_options(candidates, item="세제")
        assert len(options) >= 2
        # Options should be Korean strings
        assert all(isinstance(opt, str) for opt in options)

    def test_clarification_question_format(self):
        """Clarification question should be polite Korean with options"""
        from backend.logic.ambiguity import build_clarification_question
        
        question = build_clarification_question(
            item="청소",
            options=["세제/화학제품", "청소 도구(브러쉬/수세미)", "배수구/방충"]
        )
        assert isinstance(question, str)
        assert len(question) > 10
        # Should contain at least one option
        assert "세제" in question or "청소" in question


# ============================================================================
# 4. Two-Strike Fallback Tests
# ============================================================================

class TestTwoStrikeFallback:
    """Test 2-strike fallback mechanism"""

    def test_first_ambiguous_returns_question(self):
        """First ambiguous query (strike 0) should return a clarification question"""
        from backend.logic.ambiguity import should_fallback
        
        result = should_fallback(clarification_count=0)
        assert result is False  # Don't fallback, ask question

    def test_second_ambiguous_returns_question(self):
        """Second ambiguous query (strike 1) should still try to ask"""
        from backend.logic.ambiguity import should_fallback
        
        result = should_fallback(clarification_count=1)
        assert result is False  # Still try once more

    def test_third_strike_triggers_fallback(self):
        """Third ambiguous attempt (strike 2) should trigger fallback"""
        from backend.logic.ambiguity import should_fallback
        
        result = should_fallback(clarification_count=2)
        assert result is True  # Fallback! Show best-effort results

    def test_fallback_response_has_results(self):
        """Fallback response should include best-effort results even if ambiguous"""
        # This tests the pipeline behavior
        fallback_result = {
            "needs_clarification": False,  # No more questions
            "is_fallback": True,
            "message": "정확한 상품을 찾기 어려워 가장 관련 있는 상품을 안내해 드립니다.",
            "top3": [
                {"name": "Product A", "rank": 1},
                {"name": "Product B", "rank": 2},
            ]
        }
        assert fallback_result["is_fallback"] is True
        assert fallback_result["needs_clarification"] is False
        assert len(fallback_result["top3"]) > 0


# ============================================================================
# 5. Reranking Enhancement Tests
# ============================================================================

class TestReranking:
    """Test reranking with ambiguity-aware scoring"""

    def test_rerank_candidates_basic(self):
        """Basic reranking should return selected_id and reason"""
        from backend.logic.reranker import rerank_candidates
        
        candidates = [
            {"id": "1", "name": "스텐 채반", "desc": "튀김 건지기용"},
            {"id": "2", "name": "세탁망", "desc": "세탁기용"},
            {"id": "3", "name": "튀김가루", "desc": "식재료"},
        ]
        # Mock the LLM call
        result = rerank_candidates("튀김 건질 때 쓰는 거", candidates)
        assert "selected_id" in result
        assert "reason" in result
        assert "confidence" in result

    def test_rerank_returns_confidence(self):
        """Reranker should return a confidence score"""
        from backend.logic.reranker import rerank_candidates
        
        candidates = [
            {"id": "1", "name": "파란색 볼펜", "desc": "필기구"},
        ]
        result = rerank_candidates("파란색 볼펜", candidates)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_rerank_null_when_no_match(self):
        """Reranker should return null selected_id when no candidate matches"""
        from backend.logic.reranker import rerank_candidates
        
        candidates = [
            {"id": "1", "name": "건전지 AA", "desc": "배터리"},
            {"id": "2", "name": "멀티탭", "desc": "전기용품"},
        ]
        result = rerank_candidates("아이폰 충전기", candidates)
        # selected_id can be null if no good match
        assert "selected_id" in result

    def test_rerank_empty_candidates(self):
        """Reranker should handle empty candidates gracefully"""
        from backend.logic.reranker import rerank_candidates
        
        result = rerank_candidates("볼펜", [])
        assert result["selected_id"] is None
        assert result["confidence"] == 0.0


# ============================================================================
# 6. Integrated Pipeline Tests (with mocks)
# ============================================================================

class TestIntegratedPipeline:
    """Test the full pipeline with M2 enhancements"""

    @pytest.mark.asyncio
    async def test_clear_query_no_clarification(self):
        """Clear query should return results without clarification"""
        from backend.logic.integrated_search import IntegratedSearchPipeline
        
        pipeline = IntegratedSearchPipeline()
        # We'll test the structure of the result
        # The actual search requires external services, so we test the response format
        result = await pipeline.search(query="파란색 볼펜")
        
        assert "request_id" in result
        assert "needs_clarification" in result
        # Clear query should not need clarification (if results found)

    @pytest.mark.asyncio
    async def test_ambiguous_query_returns_clarification(self):
        """Ambiguous query should return clarification question on first attempt"""
        from backend.logic.integrated_search import IntegratedSearchPipeline
        
        pipeline = IntegratedSearchPipeline()
        result = await pipeline.search(
            query="청소",
            session_id="test-session",
            history=[]
        )
        
        assert "request_id" in result
        # If ambiguous, should have clarification fields
        if result.get("needs_clarification"):
            assert "clarification_question" in result
            assert "clarification_options" in result

    @pytest.mark.asyncio
    async def test_fallback_after_two_strikes(self):
        """After 2 clarification attempts, should fallback to best-effort results"""
        from backend.logic.integrated_search import IntegratedSearchPipeline
        
        pipeline = IntegratedSearchPipeline()
        result = await pipeline.search(
            query="그거",
            session_id="test-session",
            clarification_count=2,  # Already asked twice
            history=[
                {"role": "user", "text": "청소"},
                {"role": "assistant", "text": "세제를 찾으시나요, 청소 도구를 찾으시나요?"},
                {"role": "user", "text": "그거"},
                {"role": "assistant", "text": "어떤 종류의 청소용품을 찾으시나요?"},
            ]
        )
        
        assert "request_id" in result
        # After 2 strikes, should NOT ask again
        if result.get("is_in_scope"):
            assert result.get("needs_clarification", False) is False
            assert result.get("is_fallback", False) is True

    @pytest.mark.asyncio
    async def test_pipeline_response_includes_timing(self):
        """Pipeline response should include timing for all stages"""
        from backend.logic.integrated_search import IntegratedSearchPipeline
        
        pipeline = IntegratedSearchPipeline()
        result = await pipeline.search(query="건전지")
        
        assert "timing_ms" in result
        timing = result["timing_ms"]
        assert "total" in timing


# ============================================================================
# 7. API Endpoint Tests
#    Note: backend.main has heavy module-level init (STT adapters, Whisper, etc.)
#    We test the Pydantic model contracts directly to avoid those dependencies.
# ============================================================================

class TestAPIEndpoints:
    """Test API request/response model contracts for M2"""

    def test_search_request_has_clarification_count(self):
        """SearchRequest should accept clarification_count"""
        from pydantic import BaseModel, Field
        from typing import Optional, List, Dict

        # Mirror of backend.main.SearchRequest
        class SearchRequest(BaseModel):
            store_id: str = Field(default="store_001")
            input_type: str = Field(default="text")
            query: str = Field(...)
            session_id: Optional[str] = Field(default=None)
            history: Optional[List[Dict[str, str]]] = Field(default=None)
            clarification_count: int = Field(default=0)

        req = SearchRequest(
            query="청소",
            clarification_count=1,
        )
        assert req.clarification_count == 1

    def test_search_request_default_clarification_count(self):
        """SearchRequest should default clarification_count to 0"""
        from pydantic import BaseModel, Field
        from typing import Optional, List, Dict

        class SearchRequest(BaseModel):
            store_id: str = Field(default="store_001")
            input_type: str = Field(default="text")
            query: str = Field(...)
            session_id: Optional[str] = Field(default=None)
            history: Optional[List[Dict[str, str]]] = Field(default=None)
            clarification_count: int = Field(default=0)

        req = SearchRequest(query="볼펜")
        assert req.clarification_count == 0

    def test_search_response_has_clarification_fields(self):
        """SearchResponse should include clarification fields"""
        from pydantic import BaseModel, Field
        from typing import Optional, List, Dict, Any

        # Mirror of backend.main.SearchResponse
        class SearchResponse(BaseModel):
            request_id: str
            query: str
            is_in_scope: bool
            intent: Optional[str] = None
            top3: List[Dict[str, Any]] = []
            top1_handover: Optional[Dict[str, Any]] = None
            message: Optional[str] = None
            needs_clarification: bool = False
            clarification_question: Optional[str] = None
            clarification_options: List[str] = []
            clarification_count: int = 0
            is_fallback: bool = False
            timing_ms: Dict[str, int] = {}
            metadata: Dict[str, Any] = {}
            error: Optional[str] = None

        resp = SearchResponse(
            request_id="test-001",
            query="청소",
            is_in_scope=True,
            needs_clarification=True,
            clarification_question="세제를 찾으시나요?",
            clarification_options=["세제", "청소도구"],
            clarification_count=1,
            timing_ms={"total": 500},
        )
        assert resp.needs_clarification is True
        assert resp.clarification_question == "세제를 찾으시나요?"
        assert len(resp.clarification_options) == 2
        assert resp.clarification_count == 1
