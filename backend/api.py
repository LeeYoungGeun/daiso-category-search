# backend/api.py
"""
FastAPI STT Pipeline API
Endpoints: /health, /stt/process
v1.2 - Using faster-whisper medium model
"""

import os
import time
import uuid
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal

from poc.stt import QualityGate, PolicyGate, WhisperAdapter
from poc.stt.types import STTResult, QualityGateResult, PolicyIntent


# ============== Response Models ==============

class STTResponseData(BaseModel):
    text_raw: Optional[str]
    confidence: Optional[float]
    lang: str
    latency_ms: int
    error: Optional[str]


class QualityGateData(BaseModel):
    status: Literal["OK", "RETRY", "FAIL"]
    is_usable: bool
    reason: str


class PolicyIntentData(BaseModel):
    intent_type: Literal["PRODUCT_SEARCH", "FIXED_LOCATION", "UNSUPPORTED"]
    location_target: Optional[str]
    confidence: float
    reason: str


class STTProcessResponse(BaseModel):
    request_id: str
    stt: STTResponseData
    quality_gate: QualityGateData
    policy_intent: Optional[PolicyIntentData]
    final_response: str
    processing_time_ms: int


# ============== Global State ==============

config: dict = {}
whisper_adapter: Optional[WhisperAdapter] = None
quality_gate: Optional[QualityGate] = None
policy_gate: Optional[PolicyGate] = None


def load_config():
    """Load configuration from YAML"""
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize STT adapter and gates"""
    global config, whisper_adapter, quality_gate, policy_gate
    
    print("🚀 Starting STT Pipeline API...")
    
    # Load config
    config = load_config()
    print(f"✅ Config loaded")
    
    # Initialize Whisper adapter
    stt_config = config.get("stt", {}).get("whisper", {})
    try:
        whisper_adapter = WhisperAdapter(
            model_size=stt_config.get("model", "medium"),
            device=stt_config.get("device", "cuda"),
            compute_type=stt_config.get("compute_type", "float16"),
            fallback_model=stt_config.get("fallback_model", "small"),
            language=stt_config.get("language", "ko")
        )
    except Exception as e:
        print(f"⚠️ Whisper adapter failed to load: {e}")
        print("⚠️ STT endpoint will return simulation results")
        whisper_adapter = None
    
    # Initialize gates
    qg_config = config.get("quality_gate", {})
    quality_gate = QualityGate(
        min_chars=qg_config.get("min_chars", 2),
        min_confidence=qg_config.get("min_confidence", 0.6),
        nonsense_patterns=qg_config.get("nonsense_patterns", [])
    )
    print(f"✅ QualityGate initialized")
    
    pg_config = config.get("policy_gate", {})
    policy_gate = PolicyGate(
        fixed_locations=pg_config.get("fixed_locations", []),
        unsupported_patterns=pg_config.get("unsupported_patterns", [])
    )
    print(f"✅ PolicyGate initialized")
    
    print("🎉 STT Pipeline API ready!\n")
    
    yield
    
    print("👋 Shutting down STT Pipeline API...")


# ============== FastAPI App ==============

app = FastAPI(
    title="Daiso STT Pipeline API",
    description="AI Product Location Guide - STT → QualityGate → PolicyGate Pipeline",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정 (프론트엔드 연결용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== WebSocket ==============

from fastapi import WebSocket
from backend.ws_stt import handle_streaming_stt  # type: ignore[import-untyped]

@app.websocket("/ws/stt")
async def websocket_stt_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming STT"""
    # Accept is handled inside handle_streaming_stt or needs to be done here?
    # backend/main.py just calls the handler. Let's look at main.py again... 
    # It says "Accept the connection first" but calls the handler directly.
    # We will replicate main.py's implementation.
    await handle_streaming_stt(websocket)


# ============== Endpoints ==============

@app.get("/")
def read_root():
    return {"message": "Daiso STT Pipeline API", "status": "running"}


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "whisper_loaded": whisper_adapter is not None,
        "quality_gate": quality_gate is not None,
        "policy_gate": policy_gate is not None
    }


@app.post("/stt/process", response_model=STTProcessResponse)
async def process_stt(
    audio: UploadFile = File(...),
    attempt: int = Form(default=1)
):
    """
    Process audio file through STT pipeline
    
    - **audio**: Audio file (wav, mp3, etc.)
    - **attempt**: Attempt number (1 or 2, for retry logic)
    
    Returns STT result with quality gate and policy gate decisions
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    # Save uploaded file to temp
    temp_path = None
    try:
        suffix = Path(audio.filename).suffix if audio.filename else ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            tmp.write(content)
            temp_path = tmp.name
        
        # STT Processing
        if whisper_adapter:
            stt_result = whisper_adapter.transcribe(temp_path)
        else:
            # Simulation mode (when whisper not available)
            stt_result = STTResult(
                text_raw="(시뮬레이션 모드 - Whisper 미로드)",
                confidence=0.8,
                lang="ko",
                latency_ms=100,
                error="Whisper adapter not loaded"
            )
        
        # Quality Gate
        if quality_gate is None:
            raise HTTPException(status_code=503, detail="Quality gate not initialized")
        quality_result = quality_gate.evaluate(stt_result, attempt=attempt)
        
        # Policy Gate (only if quality OK)
        policy_intent = None
        final_response = ""
        
        if quality_result.status == "OK":
            if policy_gate is None:
                raise HTTPException(status_code=503, detail="Policy gate not initialized")
            policy_intent = policy_gate.classify(stt_result.text_raw or "")
            
            pg_config = config.get("policy_gate", {})
            
            if policy_intent.intent_type == "FIXED_LOCATION":
                # Find response for fixed location
                for loc in pg_config.get("fixed_locations", []):
                    if loc["target"] == policy_intent.location_target:
                        final_response = loc["response"]
                        break
                if not final_response:
                    final_response = f"'{policy_intent.location_target}' 위치를 안내해 드립니다."
                    
            elif policy_intent.intent_type == "UNSUPPORTED":
                final_response = pg_config.get(
                    "fallback_message", 
                    "이 서비스는 상품과 매장 내 위치 안내를 도와드리고 있어요."
                )
            else:  # PRODUCT_SEARCH
                final_response = f"[PRODUCT_SEARCH] '{stt_result.text_raw}' 검색 예정"
                
        elif quality_result.status == "RETRY":
            pg_config = config.get("policy_gate", {})
            final_response = pg_config.get(
                "retry_message",
                "말씀을 잘 듣지 못했어요. 다시 말씀해 주세요."
            )
        else:  # FAIL
            final_response = "음성 인식에 실패했습니다. 다시 시도해 주세요."
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return STTProcessResponse(
            request_id=request_id,
            stt=STTResponseData(
                text_raw=stt_result.text_raw,
                confidence=stt_result.confidence,
                lang=stt_result.lang or "ko",
                latency_ms=stt_result.latency_ms,
                error=stt_result.error
            ),
            quality_gate=QualityGateData(
                status=quality_result.status,
                is_usable=quality_result.is_usable,
                reason=quality_result.reason
            ),
            policy_intent=PolicyIntentData(
                intent_type=policy_intent.intent_type,
                location_target=policy_intent.location_target,
                confidence=policy_intent.confidence,
                reason=policy_intent.reason
            ) if policy_intent else None,
            final_response=final_response,
            processing_time_ms=processing_time_ms
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # Cleanup temp file
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
