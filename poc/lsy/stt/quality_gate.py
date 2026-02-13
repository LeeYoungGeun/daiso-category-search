# backend/stt/quality_gate.py
"""
Quality Gate Implementation
Validates STT output quality and determines RETRY/FAIL strategy
"""

import re
from typing import Dict, List, Optional

from .types import QualityGateResult, STTResult


class QualityGate:
    """
    Quality gate for STT output validation
    Implements R1→R2→R3→R4 priority-based rejection rules
    """
    
    def __init__(
        self,
        min_chars: int = 2,
        min_confidence: float = 0.6,
        nonsense_patterns: Optional[List[str]] = None
    ):
        self.min_chars = min_chars
        self.min_confidence = min_confidence
        self.nonsense_patterns = nonsense_patterns or [
            r"(ㅋ|ㅎ){3,}",
            r"(ㅇ){3,}",
            r"[!?]{3,}",
            r"^(아+|음+|어+|그+)$"
        ]
        self._compiled_patterns = [re.compile(p) for p in self.nonsense_patterns]
    
    def evaluate(
        self,
        stt_result: STTResult,
        attempt: int
    ) -> QualityGateResult:
        """
        Evaluate STT result quality
        
        Args:
            stt_result: STT transcription result
            attempt: Current attempt number (1 or 2)
            
        Returns:
            QualityGateResult with status (OK/RETRY/FAIL) and reason
            
        Raises:
            ValueError: If attempt is not 1 or 2
        """
        if attempt not in (1, 2):
            raise ValueError(f"Invalid attempt value: {attempt}. Must be 1 or 2.")
        
        text_raw = stt_result.text_raw
        confidence = stt_result.confidence
        
        # R1: EMPTY_TRANSCRIPT
        if not text_raw or text_raw.strip() == "":
            return self._make_result("EMPTY_TRANSCRIPT", attempt)
        
        # R2: TOO_SHORT
        if len(text_raw) < self.min_chars:
            return self._make_result("TOO_SHORT", attempt)
        
        # R3: NONSENSE_PATTERN
        for pattern in self._compiled_patterns:
            if pattern.search(text_raw):
                return self._make_result("NONSENSE_PATTERN", attempt)
        
        # R4: LOW_CONFIDENCE (skip if confidence is None)
        if confidence is not None and confidence < self.min_confidence:
            return self._make_result("LOW_CONFIDENCE", attempt)
        
        # All checks passed
        return QualityGateResult(
            status="OK",
            is_usable=True,
            reason="OK"
        )
    
    def _make_result(self, reason: str, attempt: int) -> QualityGateResult:
        """Helper to create RETRY/FAIL result based on attempt"""
        if attempt == 1:
            return QualityGateResult(
                status="RETRY",
                is_usable=False,
                reason=reason
            )
        else:  # attempt == 2
            return QualityGateResult(
                status="FAIL",
                is_usable=False,
                reason=reason
            )
