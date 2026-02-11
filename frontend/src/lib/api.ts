/**
 * API client for backend communication
 * - REST: /v1/search
 * - WebSocket: /ws/stt
 */

import type {
    SearchRequest,
    SearchResponse,
    STTServerMessage,
} from "@/types/search";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

// ============================================================================
// REST API: Search
// ============================================================================

export async function searchProducts(
    request: SearchRequest
): Promise<SearchResponse> {
    const body: SearchRequest = {
        store_id: request.store_id || "store_001",
        input_type: request.input_type || "text",
        query: request.query,
        session_id: request.session_id,
        history: request.history,
        clarification_count: request.clarification_count || 0,
    };

    const res = await fetch(`${API_BASE}/v1/search`, {
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

export async function healthCheck(): Promise<{
    status: string;
    [key: string]: unknown;
}> {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) {
        throw new Error(`Health check failed: ${res.status}`);
    }
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

    /**
     * Start STT session: connect WebSocket + start microphone capture
     */
    async start(): Promise<void> {
        // 1. Connect WebSocket
        this.ws = new WebSocket(`${WS_BASE}/ws/stt`);
        this.seqCounter = 0;

        this.ws.onmessage = (event) => {
            try {
                const msg: STTServerMessage = JSON.parse(event.data);
                this.handleMessage(msg);
            } catch {
                console.error("Failed to parse STT message:", event.data);
            }
        };

        this.ws.onerror = (event) => {
            console.error("WebSocket error:", event);
            this.callbacks.onError?.("WebSocket 연결 오류가 발생했습니다.");
        };

        this.ws.onclose = () => {
            this.isRecording = false;
            this.callbacks.onClose?.();
        };

        // Wait for connection
        await new Promise<void>((resolve, reject) => {
            if (!this.ws) return reject(new Error("No WebSocket"));
            this.ws.onopen = () => resolve();
            setTimeout(() => reject(new Error("WebSocket connection timeout")), 5000);
        });

        // 2. Send start message
        this.ws.send(
            JSON.stringify({
                type: "start",
                config: { sample_rate: 16000, language: "ko-KR" },
                meta: {
                    run_id: `web_${Date.now()}`,
                    test_id: `session_${Date.now()}`,
                },
            })
        );

        // 3. Start microphone capture
        await this.startMicrophone();
    }

    /**
     * Start capturing microphone audio and sending to WebSocket
     */
    private async startMicrophone(): Promise<void> {
        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });

            this.audioContext = new AudioContext({ sampleRate: 16000 });
            this.source = this.audioContext.createMediaStreamSource(this.mediaStream);

            // Use ScriptProcessorNode for PCM capture (4096 samples per buffer)
            this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
            this.isRecording = true;

            this.processor.onaudioprocess = (event) => {
                if (!this.isRecording || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
                    return;
                }

                const inputData = event.inputBuffer.getChannelData(0);

                // Convert Float32 to Int16 PCM
                const pcm16 = new Int16Array(inputData.length);
                for (let i = 0; i < inputData.length; i++) {
                    const s = Math.max(-1, Math.min(1, inputData[i]));
                    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
                }

                // Convert to base64
                const bytes = new Uint8Array(pcm16.buffer);
                let binary = "";
                for (let i = 0; i < bytes.length; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                const pcmB64 = btoa(binary);

                // Send audio chunk
                this.ws!.send(
                    JSON.stringify({
                        type: "audio",
                        pcm_b64: pcmB64,
                        seq: this.seqCounter++,
                    })
                );
            };

            this.source.connect(this.processor);
            this.processor.connect(this.audioContext.destination);
        } catch (err) {
            console.error("Microphone access error:", err);
            this.callbacks.onError?.("마이크 접근 권한이 필요합니다.");
            throw err;
        }
    }

    /**
     * Handle incoming WebSocket messages
     */
    private handleMessage(msg: STTServerMessage): void {
        switch (msg.type) {
            case "started":
                this.callbacks.onStarted?.(msg.run_id);
                break;
            case "interim":
                this.callbacks.onInterim?.(msg.text);
                break;
            case "final":
                this.callbacks.onFinal?.(
                    msg.text,
                    msg.meta?.confidence ?? 0,
                    msg.status
                );
                // Auto-stop after final result
                this.stop();
                break;
            case "error":
                this.callbacks.onError?.(msg.message);
                break;
        }
    }

    /**
     * Stop STT session: stop microphone + close WebSocket
     */
    stop(): void {
        this.isRecording = false;

        // Stop microphone
        if (this.processor) {
            this.processor.disconnect();
            this.processor = null;
        }
        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }
        if (this.audioContext) {
            this.audioContext.close().catch(() => {});
            this.audioContext = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach((track) => track.stop());
            this.mediaStream = null;
        }

        // Send stop message and close WebSocket
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify({ type: "stop" }));
            } catch {
                // ignore
            }
            this.ws.close();
        }
        this.ws = null;
    }

    /**
     * Check if currently recording
     */
    get recording(): boolean {
        return this.isRecording;
    }
}
