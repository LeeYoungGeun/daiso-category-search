# backend/ws_stt.py
"""
WebSocket endpoint for real-time streaming STT
Uses Google Cloud Speech-to-Text v1 API with SpeechHelpers signature
STT WORKER THREAD VERSION - streaming_recognize + response iteration in same thread
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

# Session configuration
MAX_SESSION_DURATION_SEC = 30
SILENCE_TIMEOUT_SEC = 3.0
SAMPLE_RATE = 16000
LANGUAGE_CODE = "ko-KR"

# Logging configuration
CSV_LOG_PATH = Path("outputs/streaming_poc_results.csv")
AUDIO_SAVE_DIR = Path("outputs/streaming_audio")
AUDIO_SAVE_ENABLED = False  # Feature flag (controlled by metadata)

# CSV Header
CSV_HEADER = [
    "timestamp", "run_id", "test_id", "utterance_type", "spoken_text_ref",
    "final_transcript", "confidence", "status", "failure_reason",
    "first_interim_latency_ms", "final_latency_ms", "duration_sec", 
    "chunk_count", "audio_path"
]

# Thread lock for CSV writing
csv_lock = threading.Lock()

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


class StreamingSTTSession:
    """
    Streaming STT session with proper thread structure:
    - WS thread: receives audio → queue.put()
    - STT worker thread: streaming_recognize + response iteration
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
        
        # Audio Buffer for saving
        self.full_audio_buffer = bytearray()
        
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
    
    async def send_final(self, text: str, confidence: float = 0.0, status: str = "OK", failure_reason: str = ""):
        self.final_ts = time.time()
        
        duration_sec = (self.final_ts - self.start_ts) if self.start_ts else 0
        final_latency_ms = int(duration_sec * 1000)
        first_interim_latency = int((self.first_interim_ts - self.start_ts) * 1000) if self.first_interim_ts and self.start_ts else None
        
        meta = {
            "confidence": round(confidence, 4),
            "latency_ms": final_latency_ms,
            "first_interim_ms": first_interim_latency,
            "duration_sec": round(duration_sec, 2)
        }
        
        await self.send_message({
            "type": "final", "text": text, "is_final": True,
            "status": status, "meta": meta
        })
        print(f"📝 final transcript: '{text}' | {status} | {confidence:.2f}")
        
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
            "final_transcript": text,
            "confidence": round(confidence, 4),
            "status": status,
            "failure_reason": failure_reason,
            "first_interim_latency_ms": first_interim_latency if first_interim_latency else "",
            "final_latency_ms": final_latency_ms,
            "duration_sec": round(duration_sec, 2),
            "chunk_count": self.chunk_count,
            "audio_path": audio_path_str
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
                
                # Buffer for saving
                if self.save_audio or AUDIO_SAVE_ENABLED:
                    self.full_audio_buffer.extend(chunk)
                
                yield StreamingRecognizeRequest(audio_content=chunk)
                
            except Empty:
                if self.stop_event.is_set():
                    break
                continue
    
    def _stt_worker_thread(self):
        """
        STT worker thread: streaming_recognize + response iteration
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
                single_utterance=False
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
                        self.result_queue.put({"type": "final", "text": text, "confidence": conf})
                        self.stop_event.set()
                        return
                    else:
                        self.result_queue.put({"type": "interim", "text": text})
            
            # Response loop ended without final
            status = "NO_SPEECH" if self.chunk_count == 0 else "TOO_SHORT"
            self.result_queue.put({"type": "final", "text": "", "confidence": 0.0, "status": status, "reason": "No final result"})
            
        except Exception as e:
            print(f"❌ STT worker error: {e}")
            traceback.print_exc()
            self.result_queue.put({"type": "error", "message": str(e)})
        finally:
            print("🔧 STT worker: thread finished")
    
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
        # Keep running until is_running becomes False (set by self or stop timeout)
        # unrelated to stop_event (which is for worker thread)
        while self.is_running:
            try:
                r = self.result_queue.get_nowait()
                if r["type"] == "interim":
                    await self.send_interim(r["text"])
                elif r["type"] == "final":
                    await self.send_final(
                        text=r["text"], 
                        confidence=r.get("confidence", 0.0), 
                        status=r.get("status", "OK"),
                        failure_reason=r.get("reason", "")
                    )
                    self.is_running = False
                    self.stop_event.set()
                elif r["type"] == "error":
                    await self.send_error(r["message"])
                    await self.send_final(text="", status="FAIL", failure_reason=r["message"]) # Log failure
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
        
        # Do not set is_running = False here. 
        # Let the worker finish and msg pass to _process_results.
        # _process_results will set is_running = False when it sees "final" or "error".
        
        # Wait for worker to finish (with timeout)
        if self.worker_thread and self.worker_thread.is_alive():
            # Run join in executor to avoid blocking event loop
            await asyncio.get_event_loop().run_in_executor(None, self.worker_thread.join, 2.0)
            if self.worker_thread.is_alive():
                print("⚠️ Worker thread still alive after timeout")
        
        # Ensure we don't hang forever if worker failed to produce result
        # Force shutdown after short grace period if still running
        for _ in range(10): 
            if not self.is_running: 
                break
            await asyncio.sleep(0.1)
        
        self.is_running = False  # Final safety force-stop


async def handle_streaming_stt(websocket: WebSocket, credentials_path: str = "backend/daisoproject-sst.json"):
    await websocket.accept()
    print("🔌 WebSocket connected")
    
    session = None
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg["type"] == "start":
                print("▶️ Start session request")
                # Extract metadata
                meta = msg.get("meta", {})
                config = msg.get("config", {})
                
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

