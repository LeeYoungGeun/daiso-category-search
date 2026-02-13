# backend/stt/types.py
"""
STT Pipeline Type Definitions
Defines data structures for STT results, quality gate, and policy gate outputs.
"""

from typing import Optional, Literal, List
from pydantic import BaseModel, Field


class STTResult(BaseModel):
    """STT transcription result from any provider"""
    text_raw: Optional[str] = None
    confidence: Optional[float] = None
    lang: Optional[str] = "ko"
    latency_ms: int
    error: Optional[str] = None


class QualityGateResult(BaseModel):
    """Quality gate evaluation result"""
    status: Literal["OK", "RETRY", "FAIL"]
    is_usable: bool
    reason: Literal[
        "EMPTY_TRANSCRIPT",
        "TOO_SHORT",
        "LOW_CONFIDENCE",
        "NONSENSE_PATTERN",
        "OK"
    ]


class PolicyIntent(BaseModel):
    """Policy gate intent classification"""
    intent_type: Literal["PRODUCT_SEARCH", "FIXED_LOCATION", "UNSUPPORTED"]
    location_target: Optional[str] = None  # For FIXED_LOCATION: "restroom", "checkout", "entrance", "exit"
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class PipelineResult(BaseModel):
    """Final result from the entire STT pipeline"""
    request_id: str
    stt: STTResult
    quality_gate: QualityGateResult
    policy_intent: Optional[PolicyIntent] = None
    normalized_text: Optional[str] = None
    final_response: str  # User-facing message
    processing_time_ms: int


# === New types for comparison ===

class ProviderResult(BaseModel):
    """Single provider STT result with full pipeline"""
    provider: str  # "whisper" or "google"
    model: str  # "medium" or "default"
    stt: STTResult
    quality_gate: QualityGateResult
    policy_intent: Optional[PolicyIntent] = None


class ComparisonPipelineResult(BaseModel):
    """Comparison result from both Whisper and Google STT"""
    request_id: str
    file_name: str
    saved_path: str
    
    # Both provider results
    whisper: ProviderResult
    google: ProviderResult
    
    # Final response (based on primary provider)
    primary_provider: str = "whisper"  # Which one to use for final_response
    final_response: str
    processing_time_ms: int
