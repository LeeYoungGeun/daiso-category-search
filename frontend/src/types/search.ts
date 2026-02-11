/**
 * TypeScript types matching the backend /v1/search API response
 */

// ============================================================================
// Search API Types
// ============================================================================

export interface SearchRequest {
    store_id?: string;
    input_type?: "text" | "voice";
    query: string;
    session_id?: string;
    history?: Array<{ role: string; content: string }>;
    clarification_count?: number;
}

export interface ProductResult {
    product_id: number | string;
    name: string;
    price: number;
    category_major: string;
    category_middle: string;
    location_text: string;
    image_url: string | null;
    rank: number;
    is_top1: boolean;
}

export interface QRHandover {
    qr_payload: string;
    expires_in_sec: number;
    product_id: number | string;
    product_name: string;
}

export interface SearchResponse {
    request_id: string;
    query: string;
    is_in_scope: boolean;
    intent: string | null;
    top3: ProductResult[];
    top1_handover: QRHandover | null;
    message: string | null;
    // M2: Clarification fields
    needs_clarification: boolean;
    clarification_question: string | null;
    clarification_options: string[];
    clarification_count: number;
    is_fallback: boolean;
    timing_ms: Record<string, number>;
    metadata: Record<string, unknown>;
    error: string | null;
}

// ============================================================================
// WebSocket STT Types
// ============================================================================

export interface STTStartMessage {
    type: "start";
    config?: {
        sample_rate?: number;
        language?: string;
    };
    meta?: {
        run_id?: string;
        test_id?: string;
        save_audio?: boolean;
        utterance_type?: string;
        spoken_text?: string;
    };
}

export interface STTAudioMessage {
    type: "audio";
    pcm_b64: string;
    seq: number;
}

export interface STTStopMessage {
    type: "stop";
}

export type STTClientMessage = STTStartMessage | STTAudioMessage | STTStopMessage;

export interface STTInterimResult {
    type: "interim";
    text: string;
    is_final: false;
}

export interface STTFinalResult {
    type: "final";
    text: string;
    is_final: true;
    status: "OK" | "NO_SPEECH" | "TOO_SHORT" | "FAIL" | "TIMEOUT" | "SILENCE";
    meta?: {
        confidence: number;
        latency_ms: number;
        first_interim_ms: number | null;
        duration_sec: number;
    };
}

export interface STTErrorResult {
    type: "error";
    message: string;
}

export interface STTStartedResult {
    type: "started";
    run_id: string;
}

export type STTServerMessage =
    | STTInterimResult
    | STTFinalResult
    | STTErrorResult
    | STTStartedResult;
