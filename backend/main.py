# backend/main.py
"""
FastAPI Server for Daiso Category Search
Integrated Pipeline: STT → NLU → Search → Rerank → Location
"""

import yaml
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException, Body, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import shutil
import time
import uuid

import sys
sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

from poc.stt.adapters import get_adapter, WhisperAdapter, GoogleAdapter
from poc.stt.quality_gate import QualityGate
from poc.stt.policy_gate import PolicyGate
from poc.stt.audio_converter import AudioConverter
from poc.stt.types import (
    PipelineResult, STTResult, QualityGateResult, PolicyIntent,
    ProviderResult, ComparisonPipelineResult
)
from backend.logic.integrated_search import get_pipeline

# Audio converter for normalizing audio to WAV/LINEAR16/16kHz/mono
audio_converter = AudioConverter(output_dir="outputs/normalized")


# Load configuration
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Initialize components
print("🔄 Initializing STT adapters...")

whisper_adapter: WhisperAdapter = get_adapter(  # type: ignore[assignment]
    "whisper",
    **config["stt"]["whisper"]
)

# Initialize Google adapter
google_config = config["stt"].get("google", {})
google_config["credentials_path"] = "backend/daisoproject-sst.json"
google_adapter: GoogleAdapter = get_adapter("google", **google_config)  # type: ignore[assignment]

quality_gate = QualityGate(
    **config["quality_gate"]
)

policy_gate = PolicyGate(
    fixed_locations=config["policy_gate"]["fixed_locations"],
    unsupported_patterns=config["policy_gate"]["unsupported_patterns"]
)

print("✅ All adapters initialized")

# Initialize integrated search pipeline
search_pipeline = get_pipeline()
print("✅ Integrated search pipeline initialized")

# FastAPI app
app = FastAPI(
    title="Daiso Category Search API",
    description="Integrated AI Search: STT → NLU → Search → Rerank → Location",
    version="2.0.0-integrated"
)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import WebSocket handler
from backend.ws_stt import handle_streaming_stt

@app.websocket("/ws/stt")
async def websocket_stt_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming STT"""
    # Accept the connection first (bypass origin check for dev)
    await handle_streaming_stt(websocket)


# ============================================================================
# Request/Response Models for /v1/search
# ============================================================================

class SearchRequest(BaseModel):
    """Request model for /v1/search endpoint"""
    store_id: str = Field(default="store_001", description="Store identifier")
    input_type: str = Field(default="text", description="Input type: text or voice")
    query: str = Field(..., description="User query text")
    session_id: Optional[str] = Field(default=None, description="Session ID for context")
    history: Optional[List[Dict[str, str]]] = Field(default=None, description="Conversation history")
    # M2: Clarification tracking
    clarification_count: int = Field(default=0, description="Number of previous clarification attempts")


class SearchResponse(BaseModel):
    """Response model for /v1/search endpoint"""
    request_id: str
    query: str
    is_in_scope: bool
    intent: Optional[str] = None
    top3: List[Dict[str, Any]] = []
    top1_handover: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    # M2: Clarification fields
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    clarification_options: List[str] = []
    clarification_count: int = 0
    is_fallback: bool = False
    timing_ms: Dict[str, int] = {}
    metadata: Dict[str, Any] = {}
    error: Optional[str] = None


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
def root():
    return {
        "service": "Daiso Category Search",
        "version": "2.0.0-integrated",
        "status": "running",
        "features": ["stt", "nlu", "search", "rerank", "location"],
        "providers": ["whisper", "google", "gemini"]
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "whisper_model": whisper_adapter.model_size,
        "google_ready": google_adapter.client is not None,
        "search_pipeline": "ready"
    }


@app.post("/v1/search", response_model=SearchResponse)
async def search_endpoint(request: SearchRequest):
    """
    Integrated search endpoint
    
    Pipeline: NLU → Keyword Expansion → Search → Rerank → Location
    
    Request:
        - store_id: Store identifier
        - input_type: "text" or "voice"
        - query: User query text
        - session_id: Optional session ID for context
        - history: Optional conversation history
    
    Response:
        - request_id: Unique request identifier
        - is_in_scope: Whether query is in scope
        - top3: Top 3 product results
        - top1_handover: QR code data for top result
        - timing_ms: Performance metrics
    """
    try:
        result = await search_pipeline.search(
            query=request.query,
            store_id=request.store_id,
            session_id=request.session_id,
            history=request.history or [],
            clarification_count=request.clarification_count,
        )
        
        return SearchResponse(**result)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )


def run_single_provider(audio_path: str, provider: str, attempt: int = 1):
    """Run STT pipeline for a single provider"""
    adapter = whisper_adapter if provider == "whisper" else google_adapter
    model = config["stt"]["whisper"]["model_size"] if provider == "whisper" else "default"
    
    # Convert audio to WAV/LINEAR16/16kHz/mono for STT
    try:
        conversion_result = audio_converter.normalize(audio_path)
        normalized_path = conversion_result["normalized_path"]
        print(f"🔄 Audio normalized: {audio_path} → {normalized_path}")
    except Exception as e:
        print(f"⚠️ Audio conversion failed, using original: {e}")
        normalized_path = audio_path
    
    # STT (use normalized path)
    stt_result = adapter.transcribe(normalized_path)
    
    # Quality Gate
    quality_result = quality_gate.evaluate(stt_result, attempt)
    
    # Policy Gate (only if OK)
    policy_intent = None
    if quality_result.status == "OK" and stt_result.text_raw:
        policy_intent = policy_gate.classify(stt_result.text_raw)
    
    return ProviderResult(
        provider=provider,
        model=model,
        stt=stt_result,
        quality_gate=quality_result,
        policy_intent=policy_intent
    )


def generate_final_response(provider_result: ProviderResult) -> str:
    """Generate final response based on provider result"""
    if provider_result.quality_gate.status == "OK":
        if provider_result.policy_intent:
            if provider_result.policy_intent.intent_type == "FIXED_LOCATION":
                for loc in config["policy_gate"]["fixed_locations"]:
                    if loc["target"] == provider_result.policy_intent.location_target:
                        return loc["response"]
            elif provider_result.policy_intent.intent_type == "UNSUPPORTED":
                return config["policy_gate"]["fallback_message"]
            else:  # PRODUCT_SEARCH
                return f"[PRODUCT_SEARCH] '{provider_result.stt.text_raw}' 검색 예정"
    elif provider_result.quality_gate.status == "RETRY":
        return config["policy_gate"]["retry_message"]
    
    return "죄송합니다. 음성을 인식할 수 없었습니다."


@app.post("/stt/compare", response_model=ComparisonPipelineResult)
async def compare_audio(
    audio: UploadFile = File(...),
    attempt: int = 1
):
    """
    Process audio through both Whisper and Google STT for comparison
    
    Returns results from both providers for performance comparison
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    # Save uploaded file
    Path("outputs").mkdir(exist_ok=True)
    
    # Use original filename if available, otherwise generate
    original_filename = audio.filename or f"recording_{request_id}.wav"
    temp_audio_path = f"outputs/temp_{request_id}_{original_filename}"
    
    print(f"📁 Saving file: {temp_audio_path}")
    
    try:
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        
        file_size = Path(temp_audio_path).stat().st_size
        print(f"📁 File saved: {file_size} bytes")
        
        # Run both providers
        print("🔄 Running Whisper STT...")
        whisper_result = run_single_provider(temp_audio_path, "whisper", attempt)
        print(f"✅ Whisper: {whisper_result.stt.text_raw}")
        
        print("🔄 Running Google STT...")
        google_result = run_single_provider(temp_audio_path, "google", attempt)
        print(f"✅ Google: {google_result.stt.text_raw}")
        
        # Generate final response (using whisper as primary by default)
        final_response = generate_final_response(whisper_result)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return ComparisonPipelineResult(
            request_id=request_id,
            file_name=original_filename,
            saved_path=temp_audio_path,
            whisper=whisper_result,
            google=google_result,
            primary_provider="whisper",
            final_response=final_response,
            processing_time_ms=processing_time_ms
        )
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Keep original endpoint for backward compatibility
@app.post("/stt/process", response_model=PipelineResult)
async def process_audio(
    audio: UploadFile = File(...),
    attempt: int = 1
):
    """
    Process audio through Whisper STT pipeline (original endpoint)
    For comparison, use /stt/compare instead
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    Path("outputs").mkdir(exist_ok=True)
    temp_audio_path = f"outputs/temp_{request_id}.wav"
    
    try:
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        
        # Step 1: STT
        stt_result = whisper_adapter.transcribe(temp_audio_path)
        
        # Step 2: Quality Gate
        quality_result = quality_gate.evaluate(stt_result, attempt)
        
        # Step 3 & 4: Policy Gate + Response Generation
        policy_intent = None
        final_response = ""
        
        if quality_result.status == "OK":
            policy_intent = policy_gate.classify(stt_result.text_raw or "")
            
            if policy_intent.intent_type == "FIXED_LOCATION":
                for loc in config["policy_gate"]["fixed_locations"]:
                    if loc["target"] == policy_intent.location_target:
                        final_response = loc["response"]
                        break
            elif policy_intent.intent_type == "UNSUPPORTED":
                final_response = config["policy_gate"]["fallback_message"]
            else:  # PRODUCT_SEARCH
                final_response = f"[PRODUCT_SEARCH] '{stt_result.text_raw}' 검색 예정"
                
        elif quality_result.status == "RETRY":
            final_response = config["policy_gate"]["retry_message"]
        else:  # FAIL
            final_response = "죄송합니다. 음성을 인식할 수 없었습니다."
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return PipelineResult(
            request_id=request_id,
            stt=stt_result,
            quality_gate=quality_result,
            policy_intent=policy_intent,
            normalized_text=stt_result.text_raw,
            final_response=final_response,
            processing_time_ms=processing_time_ms
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
