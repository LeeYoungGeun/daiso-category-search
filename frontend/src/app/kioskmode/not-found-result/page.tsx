"use client";

import { useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { searchProducts } from "@/lib/api";
import {
    setQuery,
    setSearchResponse,
    setLoading,
    setError,
    getSearchState,
} from "@/store/searchStore";

const SEARCH_SUGGESTIONS = [
    "세탁세제 어디 있어요?",
    "주방세제 위치 알려줘",
    "화장지 찾아줘",
];

function NotFoundContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const query = searchParams.get("q") || "";
    const errorMsg = getSearchState().error;

    const handleBack = useCallback(() => {
        router.back();
    }, [router]);

    const handleCallStaff = useCallback(() => {
        alert("직원을 호출했습니다. 잠시만 기다려주세요.");
    }, []);

    const handleSearchAgain = useCallback(() => {
        router.push("/kioskmode");
    }, [router]);

    const handleSuggestionClick = useCallback(
        async (suggestion: string) => {
            setQuery(suggestion);
            setLoading(true);

            try {
                const state = getSearchState();
                const response = await searchProducts({
                    query: suggestion,
                    session_id: state.sessionId,
                    history: state.history,
                    clarification_count: state.clarificationCount,
                });

                setSearchResponse(response);

                if (response.is_in_scope && response.top3.length > 0) {
                    router.push(
                        `/kioskmode/results?q=${encodeURIComponent(suggestion)}`
                    );
                } else {
                    router.replace(
                        `/kioskmode/not-found-result?q=${encodeURIComponent(suggestion)}`
                    );
                }
            } catch (err) {
                setError(
                    err instanceof Error ? err.message : "검색 오류"
                );
            }
        },
        [router]
    );

    return (
        <main className="flex min-h-screen flex-col bg-white">
            {/* Header */}
            <header className="w-full px-6 py-4">
                <button
                    onClick={handleBack}
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
            <div className="flex-1 flex flex-col items-center justify-center px-6 -mt-8">
                {/* Title */}
                <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 mb-4">
                    죄송합니다
                </h1>

                {/* Subtitle */}
                <p className="text-base sm:text-lg text-gray-500 mb-4">
                    해당 상품의 위치를 찾을 수 없습니다
                </p>

                {/* Query display */}
                {query && (
                    <p className="text-sm text-gray-400 mb-6">
                        검색어: &ldquo;{query}&rdquo;
                    </p>
                )}

                {/* Error message */}
                {errorMsg && (
                    <div className="bg-red-50 rounded-lg px-4 py-2 mb-6 max-w-md">
                        <p className="text-xs text-red-500 text-center">
                            {errorMsg}
                        </p>
                    </div>
                )}

                {/* Suggestion Box */}
                <div className="w-full max-w-md bg-gray-50 rounded-2xl p-6 mb-10">
                    <h2 className="flex items-center gap-2 text-base font-bold text-gray-800 mb-4">
                        <svg
                            width="18"
                            height="18"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                        >
                            <circle cx="12" cy="12" r="10" />
                            <line x1="12" y1="16" x2="12" y2="12" />
                            <line x1="12" y1="8" x2="12.01" y2="8" />
                        </svg>
                        이렇게 검색해 보세요:
                    </h2>
                    <ul className="space-y-2.5" role="list">
                        {SEARCH_SUGGESTIONS.map((suggestion, index) => (
                            <li key={index}>
                                <button
                                    onClick={() =>
                                        handleSuggestionClick(suggestion)
                                    }
                                    className="w-full text-left text-sm sm:text-base text-gray-600 hover:text-red-600 cursor-pointer transition-colors duration-200 focus:outline-none focus:text-red-600 rounded px-1 py-0.5"
                                >
                                    • &ldquo;{suggestion}&rdquo;
                                </button>
                            </li>
                        ))}
                    </ul>
                </div>

                {/* Action Buttons */}
                <div className="flex items-center gap-3">
                    <button
                        onClick={handleCallStaff}
                        className="flex items-center justify-center gap-2 min-w-[140px] px-6 py-3 rounded-lg border-2 border-red-200 text-red-600 font-medium cursor-pointer transition-all duration-200 hover:bg-red-50 hover:border-red-300 active:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
                    >
                        <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                        >
                            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                        </svg>
                        직원 호출
                    </button>
                    <button
                        onClick={handleSearchAgain}
                        className="flex items-center justify-center gap-2 min-w-[140px] px-6 py-3 rounded-lg bg-red-600 text-white font-medium cursor-pointer transition-all duration-200 hover:bg-red-700 active:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
                    >
                        <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                        >
                            <circle cx="11" cy="11" r="8" />
                            <line x1="21" y1="21" x2="16.65" y2="16.65" />
                        </svg>
                        다시 검색하기
                    </button>
                </div>
            </div>
        </main>
    );
}

export default function NotFoundResultPage() {
    return (
        <Suspense
            fallback={
                <main className="flex min-h-screen items-center justify-center bg-white">
                    <div className="w-12 h-12 border-4 border-red-400 border-t-transparent rounded-full animate-spin" />
                </main>
            }
        >
            <NotFoundContent />
        </Suspense>
    );
}
