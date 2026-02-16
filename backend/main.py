# backend/main.py
"""
FastAPI Server for Daiso Category Search
Integrated Pipeline: STT → NLU → Search → Rerank → Location
"""

import os
import sys
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# -------------------------------------------------------------------
# sys.path
# -------------------------------------------------------------------
sys.path.append(str(Path(__file__).parent))
sys.path.append(str(Path(__file__).parent.parent))

# -------------------------------------------------------------------
# Imports (project)
# -------------------------------------------------------------------
from poc.stt.adapters import get_adapter, WhisperAdapter, GoogleAdapter
from poc.stt.quality_gate import QualityGate
from poc.stt.policy_gate import PolicyGate
from poc.stt.audio_converter import AudioConverter
from poc.stt.types import (
    PipelineResult, STTResult, QualityGateResult, PolicyIntent,
    ProviderResult, ComparisonPipelineResult
)

from backend.logic.integrated_search import get_pipeline
from backend.search.cache import cache_health

# Import WebSocket handler
from backend.ws_stt import handle_streaming_stt

# -------------------------------------------------------------------
# Audio converter for normalizing audio to WAV/LINEAR16/16kHz/mono
# -------------------------------------------------------------------
audio_converter = AudioConverter(output_dir="outputs/normalized")

# -------------------------------------------------------------------
# Load configuration
# -------------------------------------------------------------------
config_path = Path(__file__).parent / "config.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# -------------------------------------------------------------------
# Initialize components
# -------------------------------------------------------------------
print("🔄 Initializing STT adapters...")

whisper_adapter: WhisperAdapter = get_adapter(  # type: ignore[assignment]
    "whisper",
    **config["stt"]["whisper"]
)

google_config = config["stt"].get("google", {})
google_config["credentials_path"] = "backend/daisoproject-sst.json"
google_adapter: GoogleAdapter = get_adapter("google", **google_config)  # type: ignore[assignment]

quality_gate = QualityGate(**config["quality_gate"])

policy_gate = PolicyGate(
    fixed_locations=config["policy_gate"]["fixed_locations"],
    unsupported_patterns=config["policy_gate"]["unsupported_patterns"]
)

print("✅ All adapters initialized")

search_pipeline = get_pipeline()
print("✅ Integrated search pipeline initialized")

# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------
app = FastAPI(
    title="Daiso Category Search API",
    description="Integrated AI Search: STT → NLU → Search → Rerank → Location",
    version="2.0.0-integrated"
)

# -------------------------------------------------------------------
# CORS
# - allow_credentials=True 이므로 allow_origins에 "*" 들어가면 안 됨
# - CORS_ORIGIN 환경변수는 콤마로 여러 개 받을 수 있게
# -------------------------------------------------------------------
cors_raw = os.getenv("CORS_ORIGIN", "").strip()

cors_extra: List[str] = []
if cors_raw:
    # 콤마 분리 지원
    tmp = [o.strip() for o in cors_raw.split(",") if o.strip()]
    # "*"는 credentials=True에서 금지이므로 제거
    tmp = [o for o in tmp if o != "*"]
    cors_extra = tmp

allow_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://frontend:3000",         # Docker internal
    *cors_extra,                    # e.g. http://3.39.6.105:3000
]

# 중복 제거(순서 유지)
allow_origins = list(dict.fromkeys(allow_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print(f"✅ CORS allow_origins={allow_origins}")

# -------------------------------------------------------------------
# WebSocket endpoint
# -------------------------------------------------------------------
@app.websocket("/ws/stt")
async def websocket_stt_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming STT"""
    await handle_streaming_stt(websocket)

# ============================================================================
# Request/Response Models for /v1/search
# ============================================================================
class SearchRequest(BaseModel):
    store_id: str = Field(default="store_001", description="Store identifier")
    input_type: str = Field(default="text", description="Input type: text or voice")
    query: str = Field(..., description="User query text")
    session_id: Optional[str] = Field(default=None, description="Session ID for context")
    history: Optional[List[Dict[str, str]]] = Field(default=None, description="Conversation history")
    clarification_count: int = Field(default=0, description="Number of previous clarification attempts")


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
    redis_status = cache_health()
    return {
        "status": "healthy",
        "whisper_model": whisper_adapter.model_size,
        "google_ready": google_adapter.client is not None,
        "search_pipeline": "ready",
        "redis_cache": redis_status,
    }


@app.delete("/cache")
def clear_cache():
    """Clear all Redis cache entries (daiso:* keys)"""
    try:
        from backend.search.cache import _get_redis
        client = _get_redis()
        if client is None:
            return {"status": "unavailable", "message": "Redis not connected"}

        cursor = 0
        deleted = 0
        while True:
            cursor, keys = client.scan(cursor, match="daiso:*", count=100)
            if keys:
                client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break

        return {"status": "ok", "deleted_keys": deleted}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/v1/search", response_model=SearchResponse)
async def search_endpoint(request: SearchRequest):
    """Integrated search endpoint"""
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
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


def run_single_provider(audio_path: str, provider: str, attempt: int = 1):
    adapter = whisper_adapter if provider == "whisper" else google_adapter
    model = config["stt"]["whisper"]["model_size"] if provider == "whisper" else "default"

    try:
        conversion_result = audio_converter.normalize(audio_path)
        normalized_path = conversion_result["normalized_path"]
        print(f"🔄 Audio normalized: {audio_path} → {normalized_path}")
    except Exception as e:
        print(f"⚠️ Audio conversion failed, using original: {e}")
        normalized_path = audio_path

    stt_result = adapter.transcribe(normalized_path)
    quality_result = quality_gate.evaluate(stt_result, attempt)

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
    if provider_result.quality_gate.status == "OK":
        if provider_result.policy_intent:
            if provider_result.policy_intent.intent_type == "FIXED_LOCATION":
                for loc in config["policy_gate"]["fixed_locations"]:
                    if loc["target"] == provider_result.policy_intent.location_target:
                        return loc["response"]
            elif provider_result.policy_intent.intent_type == "UNSUPPORTED":
                return config["policy_gate"]["fallback_message"]
            else:
                return f"[PRODUCT_SEARCH] '{provider_result.stt.text_raw}' 검색 예정"
    elif provider_result.quality_gate.status == "RETRY":
        return config["policy_gate"]["retry_message"]

    return "죄송합니다. 음성을 인식할 수 없었습니다."


@app.post("/stt/compare", response_model=ComparisonPipelineResult)
async def compare_audio(audio: UploadFile = File(...), attempt: int = 1):
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    Path("outputs").mkdir(exist_ok=True)

    original_filename = audio.filename or f"recording_{request_id}.wav"
    temp_audio_path = f"outputs/temp_{request_id}_{original_filename}"

    print(f"📁 Saving file: {temp_audio_path}")

    try:
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)

        file_size = Path(temp_audio_path).stat().st_size
        print(f"📁 File saved: {file_size} bytes")

        print("🔄 Running Whisper STT...")
        whisper_result = run_single_provider(temp_audio_path, "whisper", attempt)
        print(f"✅ Whisper: {whisper_result.stt.text_raw}")

        print("🔄 Running Google STT...")
        google_result = run_single_provider(temp_audio_path, "google", attempt)
        print(f"✅ Google: {google_result.stt.text_raw}")

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


@app.post("/stt/process", response_model=PipelineResult)
async def process_audio(audio: UploadFile = File(...), attempt: int = 1):
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    Path("outputs").mkdir(exist_ok=True)
    temp_audio_path = f"outputs/temp_{request_id}.wav"

    try:
        with open(temp_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)

        stt_result = whisper_adapter.transcribe(temp_audio_path)
        quality_result = quality_gate.evaluate(stt_result, attempt)

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
            else:
                final_response = f"[PRODUCT_SEARCH] '{stt_result.text_raw}' 검색 예정"

        elif quality_result.status == "RETRY":
            final_response = config["policy_gate"]["retry_message"]
        else:
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
