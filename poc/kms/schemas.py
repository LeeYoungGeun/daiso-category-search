from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field

class Intent(str, Enum):
    PRODUCT_LOCATION = "PRODUCT_LOCATION" # Search for product
    OTHER_INQUIRY = "OTHER_INQUIRY"       # General questions/Policies
    UNSUPPORTED = "UNSUPPORTED"           # Out of scope, chit-chat

class NLUSlots(BaseModel):
    item: Optional[str] = Field(default=None, description="Core product name")
    attrs: List[str] = Field(default_factory=list, description="Attributes like color, usage, size")
    category_hint: Optional[str] = Field(default=None, description="Broad category hint")
    query_rewrite: Optional[str] = Field(default=None, description="Optimized query for search engine")
    min_price: Optional[int] = Field(default=None, description="Minimum price filter")
    max_price: Optional[int] = Field(default=None, description="Maximum price filter")
    
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
    
    # Performance Metrics (added as per logging reqs)
    model_name: str = Field(default="gemini-2.0-flash")
    latency_ms: int = Field(default=0)
    token_usage: Dict[str, int] = Field(default_factory=dict) # prompt_tokens, completion_tokens
    
    # Results
    products: List[Product] = Field(default_factory=list)
