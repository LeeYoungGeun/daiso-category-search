"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { searchProducts } from "@/lib/api";
import {
    setQuery,
    setSearchResponse,
    setLoading,
    setError,
    resetSearch,
    getSearchState,
} from "@/store/searchStore";

const CATEGORIES = [
    { label: "의약품", icon: "💊" },
    { label: "문구", icon: "✏️" },
    { label: "주방", icon: "🍳" },
    { label: "생활", icon: "🏠" },
    { label: "잡화", icon: "🛒" },
] as const;

export default function KioskHome() {
    const router = useRouter();
    const [query, setQueryLocal] = useState("");
    const [isDarkMode, setIsDarkMode] = useState(false);
    const [isSearching, setIsSearching] = useState(false);

    const performSearch = useCallback(
        async (searchQuery: string, inputType: "text" | "voice" = "text") => {
            if (!searchQuery.trim()) return;

            setIsSearching(true);
            setQuery(searchQuery, inputType);
            setLoading(true);

            try {
                const state = getSearchState();
                const response = await searchProducts({
                    query: searchQuery,
                    input_type: inputType,
                    session_id: state.sessionId,
                    history: state.history,
                    clarification_count: state.clarificationCount,
                });

                setSearchResponse(response);

                // Navigate based on results
                if (!response.is_in_scope || response.error) {
                    router.push(
                        `/kioskmode/not-found-result?q=${encodeURIComponent(searchQuery)}`
                    );
                } else if (response.top3.length === 0) {
                    router.push(
                        `/kioskmode/not-found-result?q=${encodeURIComponent(searchQuery)}`
                    );
                } else {
                    router.push(
                        `/kioskmode/results?q=${encodeURIComponent(searchQuery)}`
                    );
                }
            } catch (err) {
                const errorMsg =
                    err instanceof Error ? err.message : "검색 중 오류가 발생했습니다.";
                setError(errorMsg);
                router.push(
                    `/kioskmode/not-found-result?q=${encodeURIComponent(searchQuery)}`
                );
            } finally {
                setIsSearching(false);
            }
        },
        [router]
    );

    const handleSearch = useCallback(() => {
        performSearch(query);
    }, [query, performSearch]);

    const handleCategoryClick = useCallback(
        (category: string) => {
            performSearch(`${category} 상품 찾아줘`);
        },
        [performSearch]
    );

    const handleVoiceSearch = useCallback(() => {
        resetSearch();
        router.push("/kioskmode/listening");
    }, [router]);

    return (
        <main
            className={`flex min-h-screen flex-col items-center relative transition-colors duration-300 ${
                isDarkMode ? "bg-gray-900" : "bg-white"
            }`}
        >
            {/* Header */}
            <header className="w-full flex items-center justify-between px-6 py-4">
                {/* Daiso Logo */}
                <div className="flex items-center">
                    <div
                        className="w-10 h-10 bg-red-600 rounded-sm flex items-center justify-center"
                        aria-label="다이소 로고"
                        role="img"
                    >
                        <svg
                            width="24"
                            height="24"
                            viewBox="0 0 24 24"
                            fill="white"
                            aria-hidden="true"
                        >
                            <rect x="4" y="4" width="7" height="7" rx="1" />
                            <rect x="13" y="4" width="7" height="7" rx="1" />
                            <rect x="4" y="13" width="7" height="7" rx="1" />
                            <rect x="13" y="13" width="7" height="7" rx="1" />
                        </svg>
                    </div>
                </div>

                {/* Dark Mode Toggle */}
                <button
                    onClick={() => setIsDarkMode(!isDarkMode)}
                    className="relative w-14 h-8 rounded-full cursor-pointer transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
                    style={{
                        backgroundColor: isDarkMode ? "#3B82F6" : "#D1D5DB",
                    }}
                    aria-label={isDarkMode ? "라이트 모드로 전환" : "다크 모드로 전환"}
                    role="switch"
                    aria-checked={isDarkMode}
                >
                    <span
                        className={`absolute top-1 left-1 w-6 h-6 bg-white rounded-full shadow-md transition-transform duration-200 motion-reduce:transition-none ${
                            isDarkMode ? "translate-x-6" : "translate-x-0"
                        }`}
                    />
                </button>
            </header>

            {/* Main Content */}
            <div className="flex-1 flex flex-col items-center justify-center px-4 sm:px-6 w-full max-w-2xl mx-auto -mt-8 sm:-mt-12">
                {/* Title */}
                <h1
                    className={`text-5xl sm:text-6xl md:text-7xl font-extrabold mb-3 sm:mb-4 tracking-tight transition-colors duration-300 ${
                        isDarkMode ? "text-red-500" : "text-red-600"
                    }`}
                >
                    어디다있소?
                </h1>

                {/* Subtitle */}
                <p
                    className={`text-base sm:text-lg md:text-xl mb-6 sm:mb-8 transition-colors duration-300 ${
                        isDarkMode ? "text-gray-300" : "text-gray-500"
                    }`}
                >
                    찾으시는 상품을 말씀해주세요
                </p>

                {/* Voice Search Button */}
                <button
                    onClick={handleVoiceSearch}
                    disabled={isSearching}
                    className={`w-20 h-20 sm:w-24 sm:h-24 rounded-full flex items-center justify-center shadow-lg cursor-pointer transition-all duration-200 motion-reduce:transition-none mb-8 sm:mb-10 focus:outline-none focus:ring-4 focus:ring-red-300 ${
                        isSearching
                            ? "bg-gray-400 cursor-not-allowed"
                            : "bg-red-600 hover:bg-red-700 hover:shadow-xl active:scale-95"
                    }`}
                    aria-label="음성으로 검색하기"
                >
                    {/* Question mark icon */}
                    <svg
                        width="40"
                        height="40"
                        viewBox="0 0 40 40"
                        fill="none"
                        aria-hidden="true"
                    >
                        <circle
                            cx="20"
                            cy="20"
                            r="16"
                            stroke="white"
                            strokeWidth="2"
                        />
                        <text
                            x="20"
                            y="26"
                            textAnchor="middle"
                            fill="white"
                            fontSize="22"
                            fontWeight="bold"
                            fontFamily="sans-serif"
                        >
                            ?
                        </text>
                    </svg>
                </button>

                {/* Search Input */}
                <div
                    className={`w-full flex items-center rounded-full border-2 px-4 sm:px-5 py-3 sm:py-3.5 mb-8 sm:mb-10 transition-all duration-200 ${
                        isDarkMode
                            ? "bg-gray-800 border-gray-600 focus-within:border-red-500"
                            : "bg-white border-gray-200 focus-within:border-red-400 shadow-sm focus-within:shadow-md"
                    }`}
                >
                    {/* Search icon */}
                    <svg
                        className={`w-5 h-5 mr-3 flex-shrink-0 transition-colors duration-200 ${
                            isDarkMode ? "text-gray-400" : "text-gray-400"
                        }`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                        />
                    </svg>
                    <label htmlFor="search-input" className="sr-only">
                        상품명 검색
                    </label>
                    <input
                        id="search-input"
                        type="text"
                        className={`flex-1 bg-transparent outline-none text-base sm:text-lg ${
                            isDarkMode
                                ? "text-white placeholder-gray-500"
                                : "text-gray-800 placeholder-gray-400"
                        }`}
                        placeholder="상품명을 입력하세요..."
                        value={query}
                        onChange={(e) => setQueryLocal(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                        autoComplete="off"
                        disabled={isSearching}
                    />
                    {isSearching && (
                        <div className="ml-2 w-5 h-5 border-2 border-red-400 border-t-transparent rounded-full animate-spin" />
                    )}
                    {query && !isSearching && (
                        <button
                            onClick={() => setQueryLocal("")}
                            className={`ml-2 w-6 h-6 flex items-center justify-center rounded-full cursor-pointer transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-red-400 ${
                                isDarkMode
                                    ? "text-gray-400 hover:text-white hover:bg-gray-700"
                                    : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                            }`}
                            aria-label="검색어 지우기"
                        >
                            <svg
                                width="14"
                                height="14"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2.5"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                aria-hidden="true"
                            >
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                        </button>
                    )}
                </div>

                {/* Category Buttons */}
                <nav aria-label="상품 카테고리">
                    <div className="flex flex-wrap justify-center gap-2.5 sm:gap-3">
                        {CATEGORIES.map((cat) => (
                            <button
                                key={cat.label}
                                onClick={() => handleCategoryClick(cat.label)}
                                disabled={isSearching}
                                className={`min-w-[72px] px-5 sm:px-6 py-2.5 sm:py-3 rounded-full text-sm sm:text-base font-medium cursor-pointer transition-all duration-200 motion-reduce:transition-none focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2 ${
                                    isSearching
                                        ? "opacity-50 cursor-not-allowed"
                                        : isDarkMode
                                        ? "bg-red-900/30 text-red-300 hover:bg-red-800/50 active:bg-red-800/70"
                                        : "bg-red-50 text-red-600 hover:bg-red-100 active:bg-red-200"
                                }`}
                            >
                                {cat.label}
                            </button>
                        ))}
                    </div>
                </nav>
            </div>
        </main>
    );
}
