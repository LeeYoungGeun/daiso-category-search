# backend/stt/policy_gate.py
"""
Policy Gate Implementation
Classifies query intent per 03_AI_QUERY_POLICY.md (PoC Phase 1 keyword-based)
"""

from typing import List, Dict, Optional

from .types import PolicyIntent


class PolicyGate:
    """
    Policy-based intent classification
    PoC Phase 1: Rule-based keyword matching
    """
    
    def __init__(
        self,
        fixed_locations: Optional[List[Dict]] = None,
        unsupported_patterns: Optional[List[str]] = None
    ):
        """
        Args:
            fixed_locations: List of {keyword, target, response} dicts
            unsupported_patterns: List of keywords triggering UNSUPPORTED
        """
        self.fixed_locations = fixed_locations or []
        self.unsupported_patterns = unsupported_patterns or [
            "배달", "교환", "환불", "영업시간", "반품"
        ]
    
    def classify(self, text: str) -> PolicyIntent:
        """
        Classify user query intent
        
        Priority:
        1. FIXED_LOCATION (exact match)
        2. UNSUPPORTED (운영정책 키워드)
        3. PRODUCT_SEARCH (default)
        
        Args:
            text: Normalized text from STT
            
        Returns:
            PolicyIntent with intent_type, location_target, confidence, reason
        """
        text_lower = text.lower()
        
        # Check FIXED_LOCATION
        for loc in self.fixed_locations:
            keyword = loc.get("keyword", "")
            if keyword and keyword in text:
                return PolicyIntent(
                    intent_type="FIXED_LOCATION",
                    location_target=loc.get("target"),
                    confidence=1.0,
                    reason=f"Matched fixed location keyword: '{keyword}'"
                )
        
        # Check UNSUPPORTED (store operation queries)
        for pattern in self.unsupported_patterns:
            if pattern in text:
                return PolicyIntent(
                    intent_type="UNSUPPORTED",
                    location_target=None,
                    confidence=0.9,
                    reason=f"Matched unsupported operation keyword: '{pattern}'"
                )
        
        # Default: PRODUCT_SEARCH
        return PolicyIntent(
            intent_type="PRODUCT_SEARCH",
            location_target=None,
            confidence=0.7,
            reason="No fixed location or unsupported keywords found, routing to NLU/search"
        )
