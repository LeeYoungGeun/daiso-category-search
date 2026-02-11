from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class Intent(str, Enum):
    PRODUCT_LOCATION = "PRODUCT_LOCATION"  # Search for product
    OTHER_INQUIRY = "OTHER_INQUIRY"        # General questions/Policies
    UNSUPPORTED = "UNSUPPORTED"            # Out of scope, chit-chat


class AmbiguityType(str, Enum):
    """M2: Type of ambiguity detected in user query"""
    NONE = "NONE"                        # Clear, unambiguous query
    BROAD_CATEGORY = "BROAD_CATEGORY"    # Too broad (e.g., "청소", "테이프")
    VAGUE_DESCRIPTION = "VAGUE_DESCRIPTION"  # Descriptive but unclear (e.g., "미끄러운 거")
    MULTI_INTENT = "MULTI_INTENT"        # Could mean multiple things
    NO_RESULTS = "NO_RESULTS"            # No matching products found


class NLUSlots(BaseModel):
    item: Optional[str] = Field(default=None, description="Core product name")
    attrs: List[str] = Field(default_factory=list, description="Attributes like color, usage, size")
    category_hint: Optional[str] = Field(default=None, description="Broad category hint")
    query_rewrite: Optional[str] = Field(default=None, description="Optimized query for search engine")


class Product(BaseModel):
    id: int
    name: str
    price: int
    image_url: Optional[str] = None
    rank: Optional[int] = None


class NLUResponse(BaseModel):
    request_id: str = Field(..., description="Unique ID for tracking")
    intent: Intent = Field(..., description="Classified intent")
    slots: NLUSlots = Field(default_factory=NLUSlots, description="Extracted slots")

    # Validation & Metrics
    needs_clarification: bool = Field(default=False)
    generated_question: Optional[str] = Field(default=None)

    # M2: Ambiguity detection
    ambiguity_type: AmbiguityType = Field(default=AmbiguityType.NONE, description="Type of ambiguity detected")
    confidence: float = Field(default=1.0, description="NLU confidence score (0.0-1.0)")

    # Performance Metrics (added as per logging reqs)
    model_name: str = Field(default="gemini-2.0-flash")
    latency_ms: int = Field(default=0)
    token_usage: Dict[str, int] = Field(default_factory=dict)  # prompt_tokens, completion_tokens

    # Results
    products: List[Product] = Field(default_factory=list)
