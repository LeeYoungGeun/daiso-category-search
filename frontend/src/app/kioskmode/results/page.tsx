"use client";

import { useCallback, useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { searchProducts } from "@/lib/api";
import type { ProductResult, SearchResponse } from "@/types/search";
import {
    getSearchState,
    getTopProduct,
    getRelatedProducts,
    hasResults,
    needsClarification,
    setSearchResponse,
    setQuery,
    setLoading,
    setError,
    addToHistory,
    incrementClarification,
} from "@/store/searchStore";

function formatPrice(price: number): string {
    return `₩${price.toLocaleString()}`;
}

function ResultsContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const query = searchParams.get("q") || "";

    const [topProduct, setTopProduct] = useState<ProductResult | null>(null);
    const [relatedProducts, setRelatedProducts] = useState<ProductResult[]>([]);
    const [response, setResponse] = useState<SearchResponse | null>(null);
    const [isLoading, setIsLoadingLocal] = useState(false);
    const [showClarification, setShowClarification] = useState(false);

    // Load results from store or fetch
    useEffect(() => {
        const state = getSearchState();

        if (hasResults() && state.query === query) {
            // Use cached results from store
            setTopProduct(getTopProduct());
            setRelatedProducts(getRelatedProducts());
            setResponse(state.searchResponse);
            if (needsClarification()) {
                setShowClarification(true);
            }
        } else if (query) {
            // Fetch fresh results
            setIsLoadingLocal(true);
            setQuery(query);
            setLoading(true);

            searchProducts({
                query,
                session_id: state.sessionId,
                history: state.history,
                clarification_count: state.clarificationCount,
            })
                .then((res) => {
                    setSearchResponse(res);
                    setResponse(res);
                    setTopProduct(
                        res.top3?.find((p) => p.is_top1) || res.top3?.[0] || null
                    );
                    const top1 = res.top3?.find((p) => p.is_top1) || res.top3?.[0];
                    setRelatedProducts(
                        res.top3?.filter((p) => p.product_id !== top1?.product_id) || []
                    );
                    if (res.needs_clarification) {
                        setShowClarification(true);
                    }
                    if (!res.is_in_scope || res.top3.length === 0) {
                        router.replace(
                            `/kioskmode/not-found-result?q=${encodeURIComponent(query)}`
                        );
                    }
                })
                .catch((err) => {
                    setError(
                        err instanceof Error ? err.message : "검색 오류"
                    );
                    router.replace(
                        `/kioskmode/not-found-result?q=${encodeURIComponent(query)}`
                    );
                })
                .finally(() => {
                    setIsLoadingLocal(false);
                });
        }
    }, [query, router]);

    const handleBack = useCallback(() => {
        router.back();
    }, [router]);

    const handleNavigate = useCallback(
        (product: ProductResult) => {
            const params = new URLSearchParams({
                location: product.location_text || product.category_major,
                product: product.name,
                product_id: String(product.product_id),
                price: String(product.price),
            });
            if (response?.top1_handover?.qr_payload) {
                params.set("qr", response.top1_handover.qr_payload);
            }
            router.push(`/kioskmode/navigate?${params.toString()}`);
        },
        [router, response]
    );

    const handleClarificationOption = useCallback(
        async (option: string) => {
            setShowClarification(false);
            setIsLoadingLocal(true);
            addToHistory("user", query);
            addToHistory("assistant", response?.clarification_question || "");
            addToHistory("user", option);
            incrementClarification();

            try {
                const state = getSearchState();
                const res = await searchProducts({
                    query: option,
                    session_id: state.sessionId,
                    history: state.history,
                    clarification_count: state.clarificationCount,
                });

                setSearchResponse(res);
                setResponse(res);
                setTopProduct(
                    res.top3?.find((p) => p.is_top1) || res.top3?.[0] || null
                );
                const top1 = res.top3?.find((p) => p.is_top1) || res.top3?.[0];
                setRelatedProducts(
                    res.top3?.filter((p) => p.product_id !== top1?.product_id) || []
                );
                if (res.needs_clarification) {
                    setShowClarification(true);
                }
            } catch (err) {
                setError(
                    err instanceof Error ? err.message : "검색 오류"
                );
            } finally {
                setIsLoadingLocal(false);
            }
        },
        [query, response]
    );

    // Loading state
    if (isLoading) {
        return (
            <main className="flex min-h-screen flex-col bg-gray-50">
                <header className="w-full bg-white px-6 py-4 border-b border-gray-100">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={handleBack}
                            className="flex items-center gap-1.5 text-gray-700 hover:text-gray-900 cursor-pointer transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-red-400 rounded-md px-2 py-1 -ml-2"
                            aria-label="뒤로 가기"
                        >
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <polyline points="15 18 9 12 15 6" />
                            </svg>
                            <span className="text-sm font-medium">뒤로</span>
                        </button>
                        <h1 className="text-base sm:text-lg font-medium text-gray-800">
                            검색 중...
                        </h1>
                    </div>
                </header>
                <div className="flex-1 flex items-center justify-center">
                    <div className="flex flex-col items-center gap-4">
                        <div className="w-12 h-12 border-4 border-red-400 border-t-transparent rounded-full animate-spin" />
                        <p className="text-gray-500 text-lg">
                            &ldquo;{query}&rdquo; 검색 중...
                        </p>
                    </div>
                </div>
            </main>
        );
    }

    return (
        <main className="flex min-h-screen flex-col bg-gray-50">
            {/* Header */}
            <header className="w-full bg-white px-6 py-4 border-b border-gray-100">
                <div className="flex items-center gap-3">
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
                    <h1 className="text-base sm:text-lg font-medium text-gray-800">
                        <span className="text-red-600 font-bold">
                            &ldquo;{query}&rdquo;
                        </span>{" "}
                        검색 결과
                    </h1>
                </div>
            </header>

            {/* Clarification Banner */}
            {showClarification && response?.clarification_question && (
                <div className="bg-yellow-50 border-b border-yellow-200 px-4 sm:px-6 py-4">
                    <div className="max-w-5xl mx-auto">
                        <p className="text-sm font-medium text-yellow-800 mb-3">
                            💡 {response.clarification_question}
                        </p>
                        <div className="flex flex-wrap gap-2">
                            {response.clarification_options.map((option, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => handleClarificationOption(option)}
                                    className="px-4 py-2 rounded-full bg-white border border-yellow-300 text-sm text-yellow-800 font-medium hover:bg-yellow-100 cursor-pointer transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-yellow-400"
                                >
                                    {option}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Fallback Banner */}
            {response?.is_fallback && (
                <div className="bg-blue-50 border-b border-blue-200 px-4 sm:px-6 py-3">
                    <div className="max-w-5xl mx-auto">
                        <p className="text-sm text-blue-700">
                            ℹ️ {response.message}
                        </p>
                    </div>
                </div>
            )}

            {/* Results Content */}
            <div className="flex-1 px-4 sm:px-6 py-6">
                <div className="max-w-5xl mx-auto flex flex-col lg:flex-row gap-4 sm:gap-6">
                    {/* Main Product Card */}
                    {topProduct && (
                        <div className="flex-1 lg:max-w-md">
                            <article className="bg-white rounded-2xl shadow-sm overflow-hidden">
                                {/* Product Image */}
                                <div className="w-full aspect-square bg-gray-100 flex items-center justify-center">
                                    {topProduct.image_url ? (
                                        <img
                                            src={topProduct.image_url}
                                            alt={topProduct.name}
                                            className="w-full h-full object-cover"
                                        />
                                    ) : (
                                        <svg
                                            width="64"
                                            height="64"
                                            viewBox="0 0 24 24"
                                            fill="none"
                                            stroke="#D1D5DB"
                                            strokeWidth="1"
                                            aria-hidden="true"
                                        >
                                            <rect x="3" y="3" width="18" height="18" rx="2" />
                                            <circle cx="8.5" cy="8.5" r="1.5" />
                                            <polyline points="21 15 16 10 5 21" />
                                        </svg>
                                    )}
                                </div>

                                {/* Product Info */}
                                <div className="p-5">
                                    <h2 className="text-lg sm:text-xl font-bold text-gray-900 mb-2">
                                        {topProduct.name}
                                    </h2>

                                    {/* Category */}
                                    <div className="flex items-center gap-2 mb-3 text-sm text-gray-500">
                                        <span>{topProduct.category_major}</span>
                                        {topProduct.category_middle && (
                                            <>
                                                <span className="text-gray-300">›</span>
                                                <span>{topProduct.category_middle}</span>
                                            </>
                                        )}
                                    </div>

                                    {/* Price */}
                                    <p className="text-2xl sm:text-3xl font-extrabold text-red-600 mb-4">
                                        {formatPrice(topProduct.price)}
                                    </p>

                                    {/* Location Tag */}
                                    <div className="inline-flex items-center px-4 py-2 rounded-full bg-red-50 text-red-600 text-sm font-medium mb-5">
                                        <svg
                                            width="14"
                                            height="14"
                                            viewBox="0 0 24 24"
                                            fill="currentColor"
                                            className="mr-1.5"
                                            aria-hidden="true"
                                        >
                                            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
                                        </svg>
                                        {topProduct.location_text}
                                    </div>

                                    {/* Navigate Button */}
                                    <button
                                        onClick={() => handleNavigate(topProduct)}
                                        className="w-full flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-red-600 text-white font-bold text-base cursor-pointer transition-all duration-200 hover:bg-red-700 active:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
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
                                            <polygon points="3 11 22 2 13 21 11 13 3 11" />
                                        </svg>
                                        이 위치로 안내받기
                                    </button>
                                </div>
                            </article>
                        </div>
                    )}

                    {/* Related Products */}
                    {relatedProducts.length > 0 && (
                        <div className="flex flex-col gap-4 lg:w-72">
                            {relatedProducts.map((product) => (
                                <article
                                    key={product.product_id}
                                    className="bg-white rounded-2xl shadow-sm overflow-hidden cursor-pointer transition-all duration-200 hover:shadow-md focus-within:ring-2 focus-within:ring-red-400"
                                    onClick={() => handleNavigate(product)}
                                    role="button"
                                    tabIndex={0}
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter" || e.key === " ") {
                                            e.preventDefault();
                                            handleNavigate(product);
                                        }
                                    }}
                                    aria-label={`${product.name} - ${formatPrice(product.price)} - ${product.location_text}`}
                                >
                                    <div className="flex gap-4 p-4">
                                        {/* Thumbnail */}
                                        <div className="w-20 h-20 sm:w-24 sm:h-24 bg-gray-100 rounded-lg flex-shrink-0 flex items-center justify-center">
                                            {product.image_url ? (
                                                <img
                                                    src={product.image_url}
                                                    alt={product.name}
                                                    className="w-full h-full object-cover rounded-lg"
                                                />
                                            ) : (
                                                <svg
                                                    width="32"
                                                    height="32"
                                                    viewBox="0 0 24 24"
                                                    fill="none"
                                                    stroke="#D1D5DB"
                                                    strokeWidth="1"
                                                    aria-hidden="true"
                                                >
                                                    <rect x="3" y="3" width="18" height="18" rx="2" />
                                                    <circle cx="8.5" cy="8.5" r="1.5" />
                                                    <polyline points="21 15 16 10 5 21" />
                                                </svg>
                                            )}
                                        </div>

                                        {/* Info */}
                                        <div className="flex flex-col justify-center min-w-0">
                                            <h3 className="text-sm sm:text-base font-bold text-gray-900 truncate">
                                                {product.name}
                                            </h3>
                                            <div className="flex items-center gap-1 mt-1 text-xs sm:text-sm text-red-500 font-medium">
                                                <svg
                                                    width="12"
                                                    height="12"
                                                    viewBox="0 0 24 24"
                                                    fill="currentColor"
                                                    aria-hidden="true"
                                                >
                                                    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
                                                </svg>
                                                {product.location_text}
                                            </div>
                                            <p className="text-base sm:text-lg font-extrabold text-gray-900 mt-1">
                                                {formatPrice(product.price)}
                                            </p>
                                        </div>
                                    </div>
                                </article>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* Timing info (debug) */}
            {response?.timing_ms && (
                <div className="bg-gray-100 px-4 py-2 text-xs text-gray-400 text-center">
                    검색 소요: {response.timing_ms.total}ms
                    {response.metadata?.search_mode != null && (
                        <span>{" | 모드: "}{String(response.metadata.search_mode)}</span>
                    )}
                </div>
            )}
        </main>
    );
}

export default function ResultsPage() {
    return (
        <Suspense
            fallback={
                <main className="flex min-h-screen items-center justify-center bg-gray-50">
                    <div className="w-12 h-12 border-4 border-red-400 border-t-transparent rounded-full animate-spin" />
                </main>
            }
        >
            <ResultsContent />
        </Suspense>
    );
}
