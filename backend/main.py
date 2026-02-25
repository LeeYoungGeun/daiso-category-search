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
# Lazy init holders (avoid heavy init at import time)
# -------------------------------------------------------------------
_whisper_adapter: Optional[WhisperAdapter] = None
_google_adapter: Optional[GoogleAdapter] = None
_quality_gate: Optional[QualityGate] = None
_policy_gate: Optional[PolicyGate] = None
_search_pipeline = None
_init_err: Optional[str] = None


def _init_stt_once() -> None:
    """Initialize STT-related heavy components only once (lazy)."""
    global _whisper_adapter, _google_adapter, _quality_gate, _policy_gate, _init_err
    if _whisper_adapter is not None and _google_adapter is not None and _quality_gate is not None and _policy_gate is not None:
        return
    try:
        print("🔄 Initializing STT adapters (lazy)...")

        _whisper_adapter = get_adapter(  # type: ignore[assignment]
            "whisper",
            **config["stt"]["whisper"]
        )

        google_config = config["stt"].get("google", {})
        google_config["credentials_path"] = "backend/daisoproject-sst.json"
        _google_adapter = get_adapter("google", **google_config)  # type: ignore[assignment]

        _quality_gate = QualityGate(**config["quality_gate"])

        _policy_gate = PolicyGate(
            fixed_locations=config["policy_gate"]["fixed_locations"],
            unsupported_patterns=config["policy_gate"]["unsupported_patterns"]
        )

        print("✅ STT adapters initialized (lazy)")
    except Exception as e:
        _init_err = f"stt_init_failed: {e}"
        raise


def _init_search_once():
    """Initialize search pipeline only once (lazy)."""
    global _search_pipeline, _init_err
    if _search_pipeline is not None:
        return _search_pipeline
    try:
        _search_pipeline = get_pipeline()
        print("✅ Integrated search pipeline initialized (lazy)")
        return _search_pipeline
    except Exception as e:
        _init_err = f"search_init_failed: {e}"
        raise


def _get_stt_components():
    """Convenience getter for STT components."""
    _init_stt_once()
    assert _whisper_adapter is not None and _google_adapter is not None and _quality_gate is not None and _policy_gate is not None
    return _whisper_adapter, _google_adapter, _quality_gate, _policy_gate


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
# -------------------------------------------------------------------
cors_raw = os.getenv("CORS_ORIGIN", "").strip()

cors_extra: List[str] = []
if cors_raw:
    tmp = [o.strip() for o in cors_raw.split(",") if o.strip()]
    tmp = [o for o in tmp if o != "*"]
    cors_extra = tmp

allow_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://frontend:3000",
    *cors_extra,
]

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
    _init_stt_once()
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
    rerank_mode_override: Optional[str] = Field(
        default=None,
        description="Override rerank mode per request (e.g., local/vendor/off)"
    )

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

    stt_ready = (_whisper_adapter is not None and _google_adapter is not None)
    search_ready = (_search_pipeline is not None)

    payload = {
        "status": "healthy",
        "stt": "ready" if stt_ready else "warming_up",
        "search_pipeline": "ready" if search_ready else "warming_up",
        "redis_cache": redis_status,
        "init_error": _init_err,
    }

    if stt_ready:
        try:
            payload["whisper_model"] = _whisper_adapter.model_size  # type: ignore[union-attr]
            payload["google_ready"] = (_google_adapter.client is not None)  # type: ignore[union-attr]
        except Exception:
            pass

    return payload

@app.get("/healthz")
def healthz():
    _init_stt_once()
    _init_search_once()
    return {"status": "ok"}

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
        pipeline = _init_search_once()
        result = await pipeline.search(
            query=request.query,
            store_id=request.store_id,
            session_id=request.session_id,
            history=request.history or [],
            clarification_count=request.clarification_count,
            input_type=request.input_type,
            rerank_mode_override=request.rerank_mode_override,
        )
        return SearchResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# 이하 STT compare/process 등 기존 코드 유지 (생략 가능)
# ... (너 파일에 있는 그대로 유지하면 됨)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)