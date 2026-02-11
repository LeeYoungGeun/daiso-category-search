"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { STTWebSocketClient } from "@/lib/api";
import { searchProducts } from "@/lib/api";
import {
    setQuery,
    setSearchResponse,
    setLoading,
    setError,
    getSearchState,
} from "@/store/searchStore";

export default function ListeningPage() {
    const router = useRouter();
    const [transcript, setTranscript] = useState("");
    const [interimText, setInterimText] = useState("");
    const [isListening, setIsListening] = useState(true);
    const [sttStatus, setSTTStatus] = useState<"connecting" | "listening" | "processing" | "done" | "error">("connecting");
    const [isSearching, setIsSearching] = useState(false);
    const sttClientRef = useRef<STTWebSocketClient | null>(null);

    // Start STT on mount
    useEffect(() => {
        const client = new STTWebSocketClient({
            onStarted: () => {
                setSTTStatus("listening");
            },
            onInterim: (text) => {
                setInterimText(text);
            },
            onFinal: (text, confidence, status) => {
                if (status === "OK" && text.trim()) {
                    setTranscript(text);
                    setInterimText("");
                    setSTTStatus("done");
                    setIsListening(false);
                } else if (status === "NO_SPEECH" || status === "TOO_SHORT" || status === "SILENCE") {
                    setTranscript("");
                    setInterimText("");
                    setSTTStatus("done");
                    setIsListening(false);
                } else {
                    setSTTStatus("error");
                    setIsListening(false);
                }
            },
            onError: (message) => {
                console.error("STT Error:", message);
                setSTTStatus("error");
                setIsListening(false);
            },
            onClose: () => {
                setIsListening(false);
            },
        });

        sttClientRef.current = client;

        client.start().catch((err) => {
            console.error("Failed to start STT:", err);
            setSTTStatus("error");
            setIsListening(false);
        });

        return () => {
            client.stop();
        };
    }, []);

    const handleCancel = useCallback(() => {
        sttClientRef.current?.stop();
        setIsListening(false);
        router.back();
    }, [router]);

    const handleRetry = useCallback(() => {
        // Stop current session
        sttClientRef.current?.stop();

        // Reset state
        setTranscript("");
        setInterimText("");
        setSTTStatus("connecting");
        setIsListening(true);

        // Start new session
        const client = new STTWebSocketClient({
            onStarted: () => {
                setSTTStatus("listening");
            },
            onInterim: (text) => {
                setInterimText(text);
            },
            onFinal: (text, confidence, status) => {
                if (status === "OK" && text.trim()) {
                    setTranscript(text);
                    setInterimText("");
                    setSTTStatus("done");
                    setIsListening(false);
                } else {
                    setTranscript("");
                    setSTTStatus("done");
                    setIsListening(false);
                }
            },
            onError: () => {
                setSTTStatus("error");
                setIsListening(false);
            },
            onClose: () => {
                setIsListening(false);
            },
        });

        sttClientRef.current = client;
        client.start().catch(() => {
            setSTTStatus("error");
            setIsListening(false);
        });
    }, []);

    const handleConfirm = useCallback(async () => {
        if (!transcript.trim()) return;

        setIsSearching(true);
        setQuery(transcript, "voice");
        setLoading(true);

        try {
            const state = getSearchState();
            const response = await searchProducts({
                query: transcript,
                input_type: "voice",
                session_id: state.sessionId,
                history: state.history,
                clarification_count: state.clarificationCount,
            });

            setSearchResponse(response);

            if (!response.is_in_scope || response.error || response.top3.length === 0) {
                router.push(
                    `/kioskmode/not-found-result?q=${encodeURIComponent(transcript)}`
                );
            } else {
                router.push(
                    `/kioskmode/results?q=${encodeURIComponent(transcript)}`
                );
            }
        } catch (err) {
            const errorMsg =
                err instanceof Error ? err.message : "검색 중 오류가 발생했습니다.";
            setError(errorMsg);
            router.push(
                `/kioskmode/not-found-result?q=${encodeURIComponent(transcript)}`
            );
        } finally {
            setIsSearching(false);
        }
    }, [transcript, router]);

    const displayText = transcript || interimText;

    const statusMessage = (() => {
        switch (sttStatus) {
            case "connecting":
                return "마이크에 연결 중...";
            case "listening":
                return "듣고 있습니다...";
            case "processing":
                return "처리 중...";
            case "done":
                return transcript ? `"${transcript}"` : "음성이 인식되지 않았습니다. 다시 시도해 주세요.";
            case "error":
                return "음성 인식 오류가 발생했습니다.";
            default:
                return "음성을 인식하고 있습니다...";
        }
    })();

    return (
        <main className="flex min-h-screen flex-col items-center bg-white relative">
            {/* Back Button */}
            <header className="w-full px-6 py-4">
                <button
                    onClick={handleCancel}
                    className="flex items-center gap-1.5 text-gray-700 hover:text-gray-900 cursor-pointer transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-red-400 rounded-md px-2 py-1 -ml-2"
                    aria-label="뒤로 가기"
                >
                    <svg
                        width="20"
                        height="20"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                    >
                        <polyline points="15 18 9 12 15 6" />
                    </svg>
                    <span className="text-sm font-medium">뒤로</span>
                </button>
            </header>

            {/* Main Content */}
            <div className="flex-1 flex flex-col items-center justify-center px-6 -mt-8 w-full max-w-lg mx-auto">
                {/* Title */}
                <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-gray-900 mb-8 sm:mb-10">
                    {sttStatus === "listening" ? "듣고 있습니다..." : 
                     sttStatus === "connecting" ? "연결 중..." :
                     sttStatus === "error" ? "오류 발생" :
                     transcript ? "인식 완료!" : "다시 시도해 주세요"}
                </h1>

                {/* Audio Waveform Animation */}
                <div
                    className="flex items-center justify-center gap-1 mb-10 sm:mb-12 h-16"
                    role="status"
                    aria-label="음성 인식 중"
                >
                    {[...Array(9)].map((_, i) => (
                        <span
                            key={i}
                            className={`w-1 sm:w-1.5 rounded-full ${
                                sttStatus === "error" ? "bg-gray-400" : "bg-red-600"
                            }`}
                            style={{
                                animation:
                                    isListening
                                        ? `waveform 1s ease-in-out ${i * 0.1}s infinite alternate`
                                        : "none",
                                height: isListening ? undefined : "8px",
                            }}
                        />
                    ))}
                </div>

                {/* Transcribed Text */}
                <div
                    className={`w-full rounded-full border-2 px-6 py-3.5 text-center transition-all duration-300 mb-10 sm:mb-12 ${
                        displayText
                            ? "border-gray-300 text-gray-800"
                            : sttStatus === "error"
                            ? "border-red-200 text-red-400"
                            : "border-gray-200 text-gray-400"
                    }`}
                >
                    <p className="text-base sm:text-lg">
                        {displayText
                            ? `"${displayText}"`
                            : statusMessage}
                    </p>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center gap-3">
                    <button
                        onClick={handleCancel}
                        disabled={isSearching}
                        className="min-w-[100px] px-8 py-3 rounded-lg border-2 border-gray-300 text-gray-700 font-medium cursor-pointer transition-all duration-200 hover:bg-gray-50 hover:border-gray-400 active:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2 disabled:opacity-50"
                    >
                        취소
                    </button>

                    {(sttStatus === "error" || (sttStatus === "done" && !transcript)) && (
                        <button
                            onClick={handleRetry}
                            className="min-w-[100px] px-8 py-3 rounded-lg bg-gray-600 text-white font-medium cursor-pointer transition-all duration-200 hover:bg-gray-700 active:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
                        >
                            다시 시도
                        </button>
                    )}

                    {transcript && (
                        <button
                            onClick={handleConfirm}
                            disabled={isSearching}
                            className="min-w-[100px] px-8 py-3 rounded-lg bg-red-600 text-white font-medium cursor-pointer transition-all duration-200 hover:bg-red-700 active:bg-red-800 disabled:bg-gray-300 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2 flex items-center gap-2"
                        >
                            {isSearching && (
                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            )}
                            확인
                        </button>
                    )}
                </div>
            </div>

            {/* Waveform Animation Keyframes */}
            <style jsx>{`
                @keyframes waveform {
                    0% {
                        height: 8px;
                    }
                    100% {
                        height: 48px;
                    }
                }
            `}</style>
        </main>
    );
}
