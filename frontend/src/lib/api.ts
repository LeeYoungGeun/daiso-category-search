/**
 * API client for backend communication
 * - REST: /v1/search
 * - WebSocket: /ws/stt
 *
 * 운영 권장:
 * - nginx가 동일 호스트에서 /v1, /ws 를 프록시하도록 구성되어 있으면
 *   NEXT_PUBLIC_API_URL을 비우거나(권장) http://3.39.6.105 처럼 "포트 없는" 값으로 설정한다.
 * - NEXT_PUBLIC_API_URL이 비어있으면 same-origin 상대경로로 호출한다:
 *   fetch("/v1/search"), new WebSocket("ws://{host}/ws/stt")
 */
import type { SearchRequest, SearchResponse, STTServerMessage } from "@/types/search";

const RAW_BASE = (process.env.NEXT_PUBLIC_API_URL || "").trim();
const API_BASE = RAW_BASE.length > 0 ? RAW_BASE : "";

const WS_BASE =
  API_BASE.length > 0
    ? API_BASE.replace(/^http/, "ws")
    : typeof window !== "undefined"
      ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
      : "";

// ============================================================================
// REST API: Search
// ============================================================================
export async function searchProducts(request: SearchRequest): Promise<SearchResponse> {
  const body: SearchRequest = {
    store_id: request.store_id || "store_001",
    input_type: request.input_type || "text",
    query: request.query,
    session_id: request.session_id,
    history: request.history,
    clarification_count: request.clarification_count || 0,
    // 리랭크llm 강제  ✅ 추가
    rerank_mode_override: request.rerank_mode_override,
  };

  const url = `${API_BASE}/v1/search`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Search API error (${res.status}): ${errorText}`);
  }
  return res.json();
}

// ============================================================================
// Health Check
// ============================================================================
export async function healthCheck(): Promise<{ status: string; [key: string]: unknown }> {
  const url = `${API_BASE}/health`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

// ============================================================================
// WebSocket STT Client
// ============================================================================
export interface STTCallbacks {
  onStarted?: (runId: string) => void;
  onInterim?: (text: string) => void;
  onFinal?: (text: string, confidence: number, status: string) => void;
  onError?: (message: string) => void;
  onClose?: () => void;
}

export class STTWebSocketClient {
  private ws: WebSocket | null = null;
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  private seqCounter = 0;
  private callbacks: STTCallbacks;
  private isRecording = false;

  constructor(callbacks: STTCallbacks) {
    this.callbacks = callbacks;
  }

  async start(): Promise<void> {
    const wsUrl = `${WS_BASE}/ws/stt`;
    this.ws = new WebSocket(wsUrl);
    this.seqCounter = 0;

    this.ws.onmessage = (event) => {
      try {
        const msg: STTServerMessage = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch {
        console.error("Failed to parse STT message:", event.data);
      }
    };

    this.ws.onerror = () => {
      this.callbacks.onError?.("WebSocket 연결 오류가 발생했습니다.");
    };

    this.ws.onclose = () => {
      this.isRecording = false;
      this.callbacks.onClose?.();
    };

    await new Promise<void>((resolve, reject) => {
      if (!this.ws) return reject(new Error("No WebSocket"));
      const ws = this.ws;
      const timer = setTimeout(() => reject(new Error("WebSocket connection timeout")), 5000);
      ws.onopen = () => {
        clearTimeout(timer);
        resolve();
      };
      const origOnClose = ws.onclose;
      ws.onclose = (ev) => {
        origOnClose?.call(ws, ev);
        clearTimeout(timer);
        if (ws.readyState !== WebSocket.OPEN) reject(new Error("WebSocket이 연결 전에 닫혔습니다."));
      };
    });

    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket이 이미 닫혔습니다.");
    }

    this.ws.send(
      JSON.stringify({
        type: "start",
        config: { sample_rate: 16000, language: "ko-KR" },
        meta: { run_id: `web_${Date.now()}`, test_id: `session_${Date.now()}` },
      })
    );

    await this.startMicrophone();
  }

  private async startMicrophone(): Promise<void> {
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });

      this.audioContext = new AudioContext({ sampleRate: 16000 });
      this.source = this.audioContext.createMediaStreamSource(this.mediaStream);

      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.isRecording = true;

      this.processor.onaudioprocess = (event) => {
        if (!this.isRecording || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        const inputData = event.inputBuffer.getChannelData(0);
        const pcm16 = new Int16Array(inputData.length);

        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcm16[i] = s < 0 ? (s * 0x8000) | 0 : (s * 0x7fff) | 0;
        }

        const bytes = new Uint8Array(pcm16.buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
        const pcmB64 = btoa(binary);

        this.ws!.send(JSON.stringify({ type: "audio", pcm_b64: pcmB64, seq: this.seqCounter++ }));
      };

      this.source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);
    } catch (err) {
      console.error("Microphone access error:", err);
      this.callbacks.onError?.("마이크 접근 권한이 필요합니다.");
      throw err;
    }
  }

  private handleMessage(msg: STTServerMessage): void {
    console.log("[STT recv]", msg.type, msg);
    switch (msg.type) {
      case "started":
        this.callbacks.onStarted?.(msg.run_id);
        break;
      case "interim":
        this.callbacks.onInterim?.(msg.text);
        break;
      case "final":
        this.callbacks.onFinal?.(msg.text, msg.meta?.confidence ?? 0, msg.status);
        setTimeout(() => this.stop(), 700);
        break; 
      case "error":
        this.callbacks.onError?.(msg.message);
        break;
    }
  }

  stop(): void {
    this.isRecording = false;

    if (this.processor) { this.processor.disconnect(); this.processor = null; }
    if (this.source) { this.source.disconnect(); this.source = null; }
    if (this.audioContext) { this.audioContext.close().catch(() => {}); this.audioContext = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach((t) => t.stop()); this.mediaStream = null; }

    if (this.ws) {
      try { if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "stop" })); } catch {}
      try { this.ws.close(); } catch {}
      this.ws = null;
    }
  }

  get recording(): boolean {
    return this.isRecording;
  }
}
