# backend/ws_stt.py
"""
WebSocket endpoint for real-time streaming STT
Uses Google Cloud Speech-to-Text v1 API with SpeechHelpers signature
STT WORKER THREAD VERSION - streaming_recognize + response iteration in same thread

v2: Whisper Fallback 지원
- Google Streaming 실패 시 (SILENCE stop 후 final 없음)
- Ring buffer의 PCM을 Whisper로 fallback 인식
- 프로세스 싱글톤 lazy load (동시성 대비 Lock)
"""

import asyncio
import json
import time
import base64
import threading
import struct
import traceback
import csv
import os
from dotenv import load_dotenv

load_dotenv()
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional, Iterator, Dict
from queue import Queue, Empty
from fastapi import WebSocket, WebSocketDisconnect

# v1 API imports
from google.cloud.speech_v1 import SpeechClient
from google.cloud.speech_v1.types import (
    RecognitionConfig,
    StreamingRecognitionConfig,
    StreamingRecognizeRequest
)
from google.oauth2 import service_account

# Whisper Fallback imports — canonical path via poc.stt (redirects to poc.lsy.stt)
try:
    from poc.stt.adapters import WhisperAdapter
    WHISPER_ADAPTER_AVAILABLE = True
except ImportError:
    WHISPER_ADAPTER_AVAILABLE = False
    print("⚠️ WhisperAdapter not available (faster-whisper not installed)")

# Postprocessor — canonical path via poc.stt (redirects to poc.lsy.stt)
try:
    from poc.stt.text_postprocessor import TextPostprocessor
    POSTPROCESSOR_AVAILABLE = True
except ImportError:
    POSTPROCESSOR_AVAILABLE = False
    print("⚠️ TextPostprocessor not available")


# Audio preprocessor (volume normalization, denoise)
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

try:
    import noisereduce as nr
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    NOISEREDUCE_AVAILABLE = False

# Config loader
import yaml

# Session configuration
MAX_SESSION_DURATION_SEC = 30
SILENCE_TIMEOUT_SEC = 3.0
SAMPLE_RATE = 16000
LANGUAGE_CODE = "ko-KR"

# Ring buffer default (config에서 override)
DEFAULT_BUFFER_MAX_SEC = 8

# Logging configuration
CSV_LOG_PATH = Path("outputs/streaming_poc_results.csv")
AUDIO_SAVE_DIR = Path("outputs/streaming_audio")
AUDIO_SAVE_ENABLED = False  # Feature flag (controlled by metadata)

# CSV Header
CSV_HEADER = [
    "timestamp", "run_id", "test_id", "utterance_type", "spoken_text_ref",
    "text_raw", "text_processed", "final_transcript",
    "confidence", "status", "failure_reason",
    "first_interim_latency_ms", "final_latency_ms", "duration_sec", 
    "chunk_count", "audio_path",
    "fallback_used", "fallback_provider", "fallback_latency_ms",
    "fallback_reason"
]

# Thread lock for CSV writing
csv_lock = threading.Lock()


def load_postprocessing_config() -> Dict:
    """Load postprocessing config from config.yaml"""
    candidate_paths = [
        Path(__file__).resolve().parent / "config.yaml",
        Path("backend") / "config.yaml",
       Path("config.yaml"),
    ]
    for config_path in candidate_paths:
        print(f"🔍 Trying config path: {config_path.resolve()}")
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                pp_config = config.get("postprocessing", {})
                print(f"✅ Postprocessing config loaded from: {config_path.resolve()}")
                print(f"   enabled={pp_config.get('enabled')}, apply_to_google={pp_config.get('apply_to_google')}")
                return pp_config
            except Exception as e:
                print(f"⚠️ Failed to load config from {config_path}: {e}")
        else:
            print(f"   ❌ Not found")
    print("⚠️ No config.yaml found for postprocessing")
    return {}


# 모듈 레벨 싱글톤 postprocessor (Google/Fallback 공용)
_postprocessor_instance: Optional['TextPostprocessor'] = None
_postprocessor_config: Optional[Dict] = None

def get_postprocessor() -> Optional['TextPostprocessor']:
    """싱글톤 TextPostprocessor 반환"""
    global _postprocessor_instance, _postprocessor_config
    print(f"🔍 get_postprocessor called, POSTPROCESSOR_AVAILABLE={POSTPROCESSOR_AVAILABLE}")
    if _postprocessor_instance is not None:
        print(f"✅ Returning existing postprocessor instance")
        return _postprocessor_instance
    if not POSTPROCESSOR_AVAILABLE:
        print(f"⚠️ POSTPROCESSOR_AVAILABLE is False, cannot initialize")
        return None
    try:
        _postprocessor_config = load_postprocessing_config()
        print(f"🔍 Loaded postprocessing config: enabled={_postprocessor_config.get('enabled')}")
        if not _postprocessor_config.get("enabled", True):
            print(f"⚠️ Postprocessing disabled in config")
            return None
        _postprocessor_instance = TextPostprocessor(config=_postprocessor_config)
        print(f"✅ TextPostprocessor initialized (singleton)")
        return _postprocessor_instance
    except Exception as e:
        print(f"⚠️ TextPostprocessor init failed: {e}")
        traceback.print_exc()
        return None


def load_fallback_config() -> Dict:
    """Load fallback config from config.yaml"""
    # 여러 경로 시도 (실행 위치에 따라 다를 수 있음)
    candidate_paths = [
        Path(__file__).resolve().parent / "config.yaml",          # backend/config.yaml (from ws_stt.py)
        Path("backend") / "config.yaml",                 # backend/config.yaml (from project root)
        Path("config.yaml"),                              # config.yaml (from backend/)
    ]
    
    for config_path in candidate_paths:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                fb_config = config.get("fallback", {})
                print(f"✅ Fallback config loaded from: {config_path.resolve()}")
                print(f"   enabled={fb_config.get('enabled')}, whisper={fb_config.get('whisper', {})}")
                return fb_config
            except Exception as e:
                print(f"⚠️ Failed to load config from {config_path}: {e}")
    
    print("⚠️ No config.yaml found, fallback disabled")
    return {"enabled": False}


def append_to_csv_log(row_data: Dict):
    """Thread-safe CSV append"""
    try:
        is_new = not CSV_LOG_PATH.exists()
        
        # Ensure directory exists
        CSV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        with csv_lock:
            with open(CSV_LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
                if is_new:
                    writer.writeheader()
                
                # Fill missing fields with empty string
                safe_row = {k: row_data.get(k, "") for k in CSV_HEADER}
                writer.writerow(safe_row)
                
    except Exception as e:
        print(f"❌ CSV Log Error: {e}")


# ============================================================
# WhisperFallbackManager: 프로세스 싱글톤 lazy load
# ============================================================

class WhisperFallbackManager:
    """
    프로세스 단위 싱글톤 Whisper 모델 관리.
    - 첫 fallback 요청 시 한 번만 로드
    - 이후 재사용
    - 동시 로딩/인식 방지 Lock
    """
    _instance: Optional['WhisperFallbackManager'] = None
    _init_lock = threading.Lock()
    _transcribe_lock = threading.Lock()
    
    def __init__(self):
        self.model: Optional[WhisperAdapter] = None
        self.postprocessor: Optional[TextPostprocessor] = None
        self._loaded = False
        self._fallback_config = load_fallback_config()
    
    @classmethod
    def get_instance(cls) -> 'WhisperFallbackManager':
        """Thread-safe 싱글톤 (Double-checked locking)"""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def _ensure_loaded(self):
        """Lazy load: 첫 호출 시에만 모델 로드"""
        if self._loaded:
            return
        
        with self._init_lock:
            if self._loaded:
                return
            
            whisper_cfg = self._fallback_config.get("whisper", {})
            
            if not WHISPER_ADAPTER_AVAILABLE:
                print("⚠️ WhisperAdapter not available for fallback")
                self._loaded = True
                return
            
            try:
                self.model = WhisperAdapter(
                    model_size=whisper_cfg.get("model_size", "medium"),
                    device=whisper_cfg.get("device", "cpu"),
                    compute_type=whisper_cfg.get("compute_type", "int8"),
                    fallback_model=whisper_cfg.get("fallback_model", "small"),
                    language=whisper_cfg.get("language", "ko")
                )
                print("✅ Whisper fallback model loaded (singleton)")
            except Exception as e:
                print(f"❌ Whisper fallback model load failed: {e}")
                self.model = None
            
            # Postprocessor
            if POSTPROCESSOR_AVAILABLE and self._fallback_config.get("postprocess", True):
                try:
                    config_path = Path(__file__).parent / "config.yaml"
                    with open(config_path, "r", encoding="utf-8") as f:
                        full_config = yaml.safe_load(f)
                    self.postprocessor = TextPostprocessor(
                        config=full_config.get("postprocessing", {})
                    )
                except Exception:
                    self.postprocessor = None
            
            self._loaded = True
    
    def is_available(self) -> bool:
        """Fallback 사용 가능 여부 (모델 로드 포함)"""
        if not self._fallback_config.get("enabled", False):
            print("⚠️ Fallback disabled in config")
            return False
        if not WHISPER_ADAPTER_AVAILABLE:
            print("⚠️ WhisperAdapter import not available")
            return False
        # 모델이 아직 안 로드되었으면 로드 시도
        self._ensure_loaded()
        if not self.model:
            print("⚠️ Whisper model not loaded")
            return False
        return True
    
    def transcribe_fallback(self, pcm_bytes: bytes) -> Dict:
        """
        Fallback 인식 수행 (Lock 보호)
        
        Args:
            pcm_bytes: 16kHz 16-bit mono PCM bytes
            
        Returns:
            {"text": str, "confidence": float, "latency_ms": int, "error": str|None}
        """
        self._ensure_loaded()
        
        if not self.model:
            return {
                "text": "", "confidence": 0.0, "latency_ms": 0,
                "error": "Whisper model not loaded"
            }
        
        preprocess_cfg = self._fallback_config.get("preprocess", {})
        
        # 전처리: 볼륨 정규화 + denoise (PCM bytes 단위)
        processed_bytes = pcm_bytes
        if PYDUB_AVAILABLE:
            try:
                processed_bytes = self._preprocess_pcm(
                    pcm_bytes, preprocess_cfg
                )
            except Exception as e:
                print(f"⚠️ Fallback preprocess failed, using raw: {e}")
        
        # Whisper 인식 (동시 접근 방지)
        with self._transcribe_lock:
            result = self.model.transcribe_bytes(processed_bytes, sample_rate=SAMPLE_RATE)
        
        text_raw = result.text_raw or ""
        
        # 후처리 (raw는 보존)
        text_processed = text_raw
        pp_config = load_postprocessing_config()
        if text_raw and pp_config.get("apply_to_fallback", True):
            pp = get_postprocessor()
            if pp:
                try:
                    text_processed = pp.postprocess(text_raw)
                except Exception:
                    pass
        
        return {
            "text_raw": text_raw,
            "text_processed": text_processed,
            "confidence": result.confidence or 0.0,
            "latency_ms": result.latency_ms,
            "error": result.error
        }
    
    def _preprocess_pcm(self, pcm_bytes: bytes, config: Dict) -> bytes:
        """
        PCM bytes 전처리 (볼륨 정규화 + denoise)
        파일 없이 메모리에서 처리
        """
        # PCM bytes → AudioSegment
        audio = AudioSegment(
            data=pcm_bytes,
            sample_width=2,  # 16-bit
            frame_rate=SAMPLE_RATE,
            channels=1
        )
        
        # 1. 볼륨 정규화
        if config.get("volume_normalize", True):
            target_dBFS = config.get("target_dBFS", -20.0)
            current_dBFS = audio.dBFS
            change = target_dBFS - current_dBFS
            if abs(change) > 30:
                change = 30 if change > 0 else -30
            audio = audio.apply_gain(change)
        
        # 2. Denoise
        if config.get("denoise", True) and NOISEREDUCE_AVAILABLE:
            samples = np.array(audio.get_array_of_samples())
            reduced = nr.reduce_noise(
                y=samples.astype(np.float32),
                sr=SAMPLE_RATE,
                prop_decrease=0.8,
                stationary=True
            )
            audio = audio._spawn(reduced.astype(np.int16).tobytes())
        
        # AudioSegment → PCM bytes
        return audio.raw_data


# ============================================================
# StreamingSTTSession: Google Streaming + Whisper Fallback
# ============================================================

class StreamingSTTSession:
    """
    Streaming STT session with proper thread structure:
    - WS thread: receives audio → queue.put()
    - STT worker thread: streaming_recognize + response iteration
    - Fallback: SILENCE stop 후 final 없으면 Whisper로 인식
    """
    
    def __init__(self, websocket: WebSocket, credentials_path: str, meta: dict = None):
        self.websocket = websocket
        self.credentials_path = credentials_path
        self.meta = meta or {}
        self.run_id = self.meta.get("run_id", "default_run")
        self.test_id = self.meta.get("test_id", f"test_{int(time.time())}")
        self.save_audio = self.meta.get("save_audio", False)
        
        self.client: Optional[SpeechClient] = None
        
        # Timing
        self.start_ts: Optional[float] = None
        self.first_interim_ts: Optional[float] = None
        self.final_ts: Optional[float] = None
        self.last_audio_ts: Optional[float] = None
        
        # State
        self.is_running = False
        self.stop_event = threading.Event()
        self.audio_queue: Queue = Queue()
        self.result_queue: Queue = Queue()  # For sending results to WS thread
        self.chunk_count = 0
        self.response_count = 0
        
        # Audio Ring Buffer - 항상 쌓음 (save_audio와 무관)
        self.full_audio_buffer = bytearray()
        # buffer_max_sec: config → 기본값 fallback
        fb_cfg = load_fallback_config()
        buffer_sec = fb_cfg.get("buffer_max_sec", DEFAULT_BUFFER_MAX_SEC)
        self._buffer_max_bytes = SAMPLE_RATE * 2 * buffer_sec
        print(f"📦 Ring buffer: {buffer_sec}sec ({self._buffer_max_bytes} bytes)")
        
        # Postprocessor 참조 (싱글톤)
        self._postprocessor = get_postprocessor()
        self._pp_config = load_postprocessing_config()
        
        # Fallback state
        self._fallback_triggered = False  # 세션 단위 중복 방지
        self._got_final = False  # final 결과 수신 여부
        self._fallback_result: Optional[Dict] = None
        self.force_fallback = self.meta.get("force_fallback", False)  # 테스트용 강제 Fallback
        
        # Thread reference
        self.worker_thread = None
        
    async def initialize(self):
        """Initialize Google STT client"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                self.credentials_path
            )
            self.client = SpeechClient(credentials=credentials)
            print(f"✅ STT client initialized (RunID: {self.run_id}, TestID: {self.test_id})")
            return True
        except Exception as e:
            print(f"❌ STT init failed: {e}")
            traceback.print_exc()
            await self.send_error(str(e))
            return False
    
    async def send_message(self, msg: dict):
        try:
            await self.websocket.send_json(msg)
        except Exception as e:
            print(f"❌ Send failed: {e}")
    
    async def send_error(self, msg: str):
        await self.send_message({"type": "error", "message": msg})
    
    async def send_interim(self, text: str):
        if self.first_interim_ts is None:
            self.first_interim_ts = time.time()
        await self.send_message({"type": "interim", "text": text, "is_final": False})
    
    async def send_final(
        self, text_raw: str = "", text_processed: str = "",
        confidence: float = 0.0, 
        status: str = "OK", failure_reason: str = "",
        fallback_used: bool = False, fallback_provider: str = "",
        fallback_latency_ms: int = 0, fallback_reason: str = ""
    ):
        self.final_ts = time.time()
        
        # 최종 text는 text_processed (없으면 text_raw)
        text = text_processed if text_processed else text_raw
        
        duration_sec = (self.final_ts - self.start_ts) if self.start_ts else 0
        final_latency_ms = int(duration_sec * 1000)
        first_interim_latency = int((self.first_interim_ts - self.start_ts) * 1000) if self.first_interim_ts and self.start_ts else None
        
        meta = {
            "confidence": round(confidence, 4),
            "latency_ms": final_latency_ms,
            "first_interim_ms": first_interim_latency,
            "duration_sec": round(duration_sec, 2),
            "text_raw": text_raw,
            "text_processed": text_processed,
            "fallback_used": fallback_used,
            "fallback_provider": fallback_provider,
            "fallback_latency_ms": fallback_latency_ms,
            "fallback_reason": fallback_reason
        }
        
        await self.send_message({
            "type": "final", "text": text, "is_final": True,
            "status": status, "meta": meta
        })
        print(f"📝 final: raw='{text_raw}' | processed='{text_processed}' | {status} | conf={confidence:.2f} | fallback={fallback_used}")
        
        # 1. Save Audio if enabled
        audio_path_str = ""
        if self.save_audio or AUDIO_SAVE_ENABLED:
            try:
                AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
                filename = f"{self.run_id}_{self.test_id}.wav"
                # Sanitize filename
                filename = "".join(c for c in filename if c.isalnum() or c in ('-', '_', '.'))
                save_path = AUDIO_SAVE_DIR / filename
                
                # Write simple WAV header + PCM
                with open(save_path, "wb") as f:
                    # WAV Header
                    f.write(struct.pack('<4sI4s', b'RIFF', 36 + len(self.full_audio_buffer), b'WAVE'))
                    f.write(struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16))
                    f.write(struct.pack('<4sI', b'data', len(self.full_audio_buffer)))
                    f.write(self.full_audio_buffer)
                
                audio_path_str = str(save_path)
                print(f"💾 Audio saved: {audio_path_str}")
            except Exception as e:
                print(f"❌ Failed to save audio: {e}")

        # 2. Log to CSV
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "test_id": self.test_id,
            "utterance_type": self.meta.get("utterance_type", ""),
            "spoken_text_ref": self.meta.get("spoken_text", ""),
            "text_raw": text_raw,
            "text_processed": text_processed,
            "final_transcript": text,
            "confidence": round(confidence, 4),
            "status": status,
            "failure_reason": failure_reason,
            "first_interim_latency_ms": first_interim_latency if first_interim_latency else "",
            "final_latency_ms": final_latency_ms,
            "duration_sec": round(duration_sec, 2),
            "chunk_count": self.chunk_count,
            "audio_path": audio_path_str,
            "fallback_used": fallback_used,
            "fallback_provider": fallback_provider,
            "fallback_latency_ms": fallback_latency_ms,
            "fallback_reason": fallback_reason
        }
        append_to_csv_log(log_data)
    
    def _audio_generator(self) -> Iterator[StreamingRecognizeRequest]:
        """
        Queue-based audio generator (runs in STT worker thread).
        """
        print(f"🎤 Audio generator started (Queue size: {self.audio_queue.qsize()})")
        
        while not self.stop_event.is_set():
            try:
                # Block waiting for audio from WS thread
                chunk = self.audio_queue.get(timeout=0.2)
                
                # Poison pill check
                if chunk is None:
                    break
                
                self.chunk_count += 1
                
                # Ring buffer: 항상 쌓기 (save_audio 무관)
                self.full_audio_buffer.extend(chunk)
                # Ring buffer max 유지
                if len(self.full_audio_buffer) > self._buffer_max_bytes:
                    overflow = len(self.full_audio_buffer) - self._buffer_max_bytes
                    del self.full_audio_buffer[:overflow]
                
                yield StreamingRecognizeRequest(audio_content=chunk)
                
            except Empty:
                if self.stop_event.is_set():
                    break
                continue
    
    def _stt_worker_thread(self):
        """
        STT worker thread: streaming_recognize + response iteration
        Fallback은 여기서 트리거하지 않음 (_process_results에서 처리)
        """
        print("🔧 STT worker: thread started")
        
        try:
            recognition_config = RecognitionConfig(
                encoding=RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=SAMPLE_RATE,
                language_code=LANGUAGE_CODE,
                enable_automatic_punctuation=True,
            )
            
            streaming_config = StreamingRecognitionConfig(
                config=recognition_config,
                interim_results=True,
                single_utterance=True,
            )
            
            responses = self.client.streaming_recognize(
                config=streaming_config,
                requests=self._audio_generator()
            )
            
            for response in responses:
                self.response_count += 1
                
                for result in response.results:
                    if not result.alternatives:
                        continue
                    
                    alt = result.alternatives[0]
                    text = alt.transcript
                    conf = getattr(alt, 'confidence', 0.0)
                    
                    if result.is_final:
                        self._got_final = True
                        if self.force_fallback:
                            # 강제 Fallback 모드: Google final 무시 → Whisper로
                            print(f"🔧 force_fallback=True → Google final 무시: '{text}'")
                            self.result_queue.put({
                                "type": "final", "text": "", "confidence": 0.0,
                                "status": "FORCE_FALLBACK", "reason": "force_fallback enabled",
                                "needs_fallback": True,
                                "google_text": text, "google_confidence": conf
                            })
                        else:
                            self.result_queue.put({"type": "final", "text": text, "confidence": conf})
                        self.stop_event.set()
                        return
                    else:
                        self.result_queue.put({"type": "interim", "text": text})
            
            # Response loop ended without final
            status = "NO_SPEECH" if self.chunk_count == 0 else "TOO_SHORT"
            self.result_queue.put({
                "type": "final", "text": "", "confidence": 0.0, 
                "status": status, "reason": "No final result",
                "needs_fallback": True  # Fallback 필요 표시
            })
            
        except Exception as e:
            print(f"❌ STT worker error: {e}")
            traceback.print_exc()
            self.result_queue.put({
                "type": "error", "message": str(e),
                "needs_fallback": True
            })
        finally:
            print("🔧 STT worker: thread finished")
    
    def _run_whisper_fallback(self) -> Dict:
        """
        Whisper fallback 실행 (동기, worker thread에서 호출 가능)
        
        Returns:
            {"text": str, "confidence": float, "latency_ms": int, 
             "provider": str, "error": str|None}
        """
        manager = WhisperFallbackManager.get_instance()
        
        if not manager.is_available():
            return {
                "text": "", "confidence": 0.0, "latency_ms": 0,
                "provider": "whisper", "error": "Fallback not available"
            }
        
        buffer_bytes = bytes(self.full_audio_buffer)
        buffer_duration_sec = len(buffer_bytes) / (SAMPLE_RATE * 2)
        print(f"🔄 Whisper fallback: {len(buffer_bytes)} bytes ({buffer_duration_sec:.1f}s)")
        
        if len(buffer_bytes) < 3200:  # 최소 100ms
            return {
                "text": "", "confidence": 0.0, "latency_ms": 0,
                "provider": "whisper", "error": "Buffer too short"
            }
        
        result = manager.transcribe_fallback(buffer_bytes)
        result["provider"] = "whisper"
        return result
    
    async def process_audio(self, pcm_b64: str, seq: int):
        """Called from WS thread - puts audio into queue for worker"""
        try:
            audio = base64.b64decode(pcm_b64)
            self.audio_queue.put(audio)
            self.last_audio_ts = time.time()
        except:
            pass
    
    async def start(self):
        self.is_running = True
        self.start_ts = time.time()
        self.stop_event.clear()
        
        self.worker_thread = threading.Thread(target=self._stt_worker_thread, daemon=True)
        self.worker_thread.start()
        
        asyncio.create_task(self._process_results())
        asyncio.create_task(self._monitor_session())
    
    async def _process_results(self):
        """Process results from STT worker and send to WS"""
        while self.is_running:
            try:
                r = self.result_queue.get_nowait()
                if r["type"] == "interim":
                    await self.send_interim(r["text"])
                elif r["type"] == "final":
                    text_raw = r["text"]
                    confidence = r.get("confidence", 0.0)
                    status = r.get("status", "OK")
                    reason = r.get("reason", "")
                    needs_fallback = r.get("needs_fallback", False)
                    
                    fallback_used = False
                    fallback_provider = ""
                    fallback_latency_ms = 0
                    fallback_reason = ""
                    
                    # Fallback 판정
                    if (
                        needs_fallback and
                        (not text_raw or text_raw.strip() == "") and
                        not self._fallback_triggered and
                        len(self.full_audio_buffer) > 3200
                    ):
                        self._fallback_triggered = True
                        
                        # fallback_reason 표준화
                        if self.force_fallback:
                            fallback_reason = "FORCE"
                        elif status in ("NO_SPEECH", "TOO_SHORT"):
                            fallback_reason = "SILENCE_NO_FINAL"
                        else:
                            fallback_reason = "SILENCE_NO_FINAL"
                        
                        print(f"🔄 Triggering Whisper fallback (reason: {fallback_reason})...")
                        
                        fb_result = await asyncio.get_event_loop().run_in_executor(
                            None, self._run_whisper_fallback
                        )
                        
                        if fb_result.get("text_raw") or fb_result.get("text_processed"):
                            text_raw = fb_result.get("text_raw", "")
                            confidence = fb_result.get("confidence", 0.0)
                            status = "FALLBACK_OK"
                            reason = ""
                            fallback_used = True
                            fallback_provider = fb_result.get("provider", "whisper")
                            fallback_latency_ms = fb_result.get("latency_ms", 0)
                            print(f"✅ Fallback success: raw='{text_raw}'")
                        else:
                            status = "FALLBACK_FAIL"
                            reason = fb_result.get("error", "Fallback returned empty")
                            fallback_used = True
                            fallback_provider = "whisper"
                            fallback_latency_ms = fb_result.get("latency_ms", 0)
                            print(f"❌ Fallback failed: {reason}")
                    
                    # postprocess 적용
                    text_processed = text_raw
                    if fallback_used:
                        # Fallback 결과에는 이미 processed 포함
                        text_processed = fb_result.get("text_processed", text_raw)
                    elif text_raw and self._pp_config.get("apply_to_google", True):
                        pp = get_postprocessor()
                        if pp:
                            try:
                                text_processed = pp.postprocess(text_raw)
                            except Exception:
                                pass
                    
                    await self.send_final(
                        text_raw=text_raw, text_processed=text_processed,
                        confidence=confidence,
                        status=status, failure_reason=reason,
                        fallback_used=fallback_used,
                        fallback_provider=fallback_provider,
                        fallback_latency_ms=fallback_latency_ms,
                        fallback_reason=fallback_reason
                    )
                    self.is_running = False
                    self.stop_event.set()
                    
                elif r["type"] == "error":
                    needs_fallback = r.get("needs_fallback", False)
                    error_msg = r["message"]
                    
                    fallback_used = False
                    fallback_provider = ""
                    fallback_latency_ms = 0
                    fallback_reason = ""
                    text_raw = ""
                    text_processed = ""
                    status = "FAIL"
                    
                    # Error에서도 fallback 시도
                    if (
                        needs_fallback and
                        not self._fallback_triggered and
                        len(self.full_audio_buffer) > 3200
                    ):
                        self._fallback_triggered = True
                        fallback_reason = "GOOGLE_ERROR"
                        print(f"🔄 Triggering Whisper fallback (reason: {fallback_reason}, error: {error_msg})...")
                        
                        fb_result = await asyncio.get_event_loop().run_in_executor(
                            None, self._run_whisper_fallback
                        )
                        
                        if fb_result.get("text_raw") or fb_result.get("text_processed"):
                            text_raw = fb_result.get("text_raw", "")
                            text_processed = fb_result.get("text_processed", text_raw)
                            status = "FALLBACK_OK"
                            error_msg = ""
                            fallback_used = True
                            fallback_provider = fb_result.get("provider", "whisper")
                            fallback_latency_ms = fb_result.get("latency_ms", 0)
                            print(f"✅ Fallback success: raw='{text_raw}'")
                        else:
                            fallback_used = True
                            fallback_provider = "whisper"
                            fallback_latency_ms = fb_result.get("latency_ms", 0)
                            status = "FALLBACK_FAIL"
                            print(f"❌ Fallback also failed")
                    
                    if not fallback_used:
                        await self.send_error(error_msg)
                    
                    await self.send_final(
                        text_raw=text_raw, text_processed=text_processed,
                        status=status, failure_reason=error_msg,
                        fallback_used=fallback_used,
                        fallback_provider=fallback_provider,
                        fallback_latency_ms=fallback_latency_ms,
                        fallback_reason=fallback_reason
                    )
                    self.is_running = False
                    self.stop_event.set()
                    
            except Empty:
                await asyncio.sleep(0.05)
    
    async def _monitor_session(self):
        """Monitor for timeout conditions"""
        while self.is_running and not self.stop_event.is_set():
            await asyncio.sleep(0.1)
            now = time.time()
            
            if self.start_ts and (now - self.start_ts) >= MAX_SESSION_DURATION_SEC:
                await self.stop("TIMEOUT")
                return
            
            if self.last_audio_ts and (now - self.last_audio_ts) >= SILENCE_TIMEOUT_SEC:
                await self.stop("SILENCE")
                return
    
    async def stop(self, reason: str = "USER_STOP"):
        if self.stop_event.is_set():
            return
            
        print(f"🛑 Stopping session: {reason}")
        self.stop_event.set()

        # Inject ~500ms of silence to help STT finalize the last utterance
        # 16000 Hz * 2 bytes/sample * 0.5s = 16000 bytes
        silence_frame = b'\x00' * 16000
        self.audio_queue.put(silence_frame)

        self.audio_queue.put(None)  # Poison pill
        
        # Wait for worker to finish (with timeout)
        if self.worker_thread and self.worker_thread.is_alive():
            await asyncio.get_event_loop().run_in_executor(None, self.worker_thread.join, 2.0)
            if self.worker_thread.is_alive():
                print("⚠️ Worker thread still alive after timeout")
        
        # Ensure we don't hang forever if worker failed to produce result
        for _ in range(10): 
            if not self.is_running: 
                break
            await asyncio.sleep(0.1)
        
        self.is_running = False  # Final safety force-stop


async def handle_streaming_stt(websocket: WebSocket, credentials_path: str = None):
    await websocket.accept()
    print("🔌 WebSocket connected")
    
    session = None
    
    try:
        while True:            
            data = await websocket.receive_text()
            if not data or not data.strip():
                continue
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "INVALID_JSON"})
                continue
            
            
            if msg["type"] == "start":
                print("▶️ Start session request")
                # Extract metadata
                meta = msg.get("meta", {})
                config = msg.get("config", {})
                
                # Resolve credentials path
                if not credentials_path:
                    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                
                if not credentials_path:
                    # Fallback default (legacy)
                    credentials_path = "backend/daisoproject-sst.json"

                session = StreamingSTTSession(websocket, credentials_path, meta=meta)
                if await session.initialize():
                    await session.start()
                    await websocket.send_json({"type": "started", "run_id": session.run_id})
                else:
                    await websocket.send_json({"type": "error", "message": "Init failed"})
                    
            elif msg["type"] == "audio" and session:
                await session.process_audio(msg.get("pcm_b64", ""), msg.get("seq", 0))
                
            elif msg["type"] == "stop" and session:
                await session.stop("USER_STOP")
                session = None
                
    except WebSocketDisconnect:
        print("🔌 Disconnected")
        if session:
            await session.stop("DISCONNECT")
    except RuntimeError as e:
        if "WebSocket is not connected" in str(e):
            print("🔌 Disconnected (Client closed)")
            if session:
                await session.stop("DISCONNECT")
        else:
            print(f"❌ Runtime error: {e}")
            traceback.print_exc()
            if session:
                await session.stop("ERROR")
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        traceback.print_exc()
        if session:
            await session.stop("ERROR")
