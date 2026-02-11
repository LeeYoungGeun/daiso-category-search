"use client";

import { useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function MobileMapContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const product = searchParams.get("product") || "상품";
    const location = searchParams.get("location") || "매장 내";
    const productId = searchParams.get("product_id") || "";

    const handleBack = useCallback(() => {
        router.back();
    }, [router]);

    const handleArrived = useCallback(() => {
        const params = new URLSearchParams({
            product,
            location,
            product_id: productId,
        });
        router.push(`/mobile/arrived?${params.toString()}`);
    }, [router, product, location, productId]);

    // Parse location for display
    const locationParts = location.split(" > ");
    const locationDisplay = locationParts[locationParts.length - 1] || location;

    return (
        <main className="flex min-h-screen flex-col bg-white max-w-md mx-auto">
            {/* Status Bar Placeholder */}
            <div className="flex items-center justify-between px-5 py-2 text-xs text-gray-800">
                <span className="font-medium">
                    {new Date().getHours().toString().padStart(2, "0")}:
                    {new Date().getMinutes().toString().padStart(2, "0")}
                </span>
                <div className="flex items-center gap-1">
                    <svg
                        width="16"
                        height="12"
                        viewBox="0 0 16 12"
                        fill="#111"
                        aria-hidden="true"
                    >
                        <rect x="0" y="8" width="3" height="4" rx="0.5" />
                        <rect x="4" y="5" width="3" height="7" rx="0.5" />
                        <rect x="8" y="2" width="3" height="10" rx="0.5" />
                        <rect x="12" y="0" width="3" height="12" rx="0.5" />
                    </svg>
                    <svg
                        width="16"
                        height="12"
                        viewBox="0 0 24 16"
                        fill="#111"
                        aria-hidden="true"
                    >
                        <rect
                            x="1"
                            y="4"
                            width="20"
                            height="10"
                            rx="2"
                            stroke="#111"
                            strokeWidth="1.5"
                            fill="none"
                        />
                        <rect x="22" y="7" width="2" height="4" rx="0.5" />
                        <rect x="3" y="6" width="14" height="6" rx="1" fill="#111" />
                    </svg>
                </div>
            </div>

            {/* Header */}
            <header className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
                <button
                    onClick={handleBack}
                    className="flex items-center gap-1 text-gray-700 hover:text-gray-900 cursor-pointer transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-red-400 rounded-md px-1 py-0.5"
                    aria-label="뒤로 가기"
                >
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
                        <polyline points="15 18 9 12 15 6" />
                    </svg>
                    <span className="text-sm">뒤로</span>
                </button>
                <h1 className="text-base font-bold flex items-center gap-1.5">
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
                        <polygon points="3 11 22 2 13 21 11 13 3 11" />
                    </svg>
                    지도 안내
                </h1>
                <div className="w-14" />
            </header>

            {/* Map Area */}
            <div
                className="flex-1 bg-green-50 relative min-h-[300px]"
                role="img"
                aria-label={`매장 내 지도 - 현재 위치에서 ${locationDisplay}까지 안내`}
            >
                {/* Simplified map visualization */}
                <div className="absolute inset-0 flex items-center justify-center">
                    <div className="relative w-full h-full">
                        {/* Grid lines for map feel */}
                        <div className="absolute inset-0 opacity-10">
                            {[...Array(8)].map((_, i) => (
                                <div
                                    key={`h-${i}`}
                                    className="absolute w-full border-t border-gray-400"
                                    style={{ top: `${(i + 1) * 12.5}%` }}
                                />
                            ))}
                            {[...Array(6)].map((_, i) => (
                                <div
                                    key={`v-${i}`}
                                    className="absolute h-full border-l border-gray-400"
                                    style={{ left: `${(i + 1) * 16.67}%` }}
                                />
                            ))}
                        </div>

                        {/* Current location marker */}
                        <div className="absolute bottom-[30%] left-[25%] flex flex-col items-center">
                            <div className="w-4 h-4 bg-blue-500 rounded-full border-2 border-white shadow-lg" />
                            <span className="text-[10px] text-blue-600 font-medium mt-1 bg-white/80 px-1 rounded">
                                현재
                            </span>
                        </div>

                        {/* Destination marker */}
                        <div className="absolute top-[25%] right-[25%] flex flex-col items-center">
                            <svg
                                width="24"
                                height="32"
                                viewBox="0 0 24 32"
                                fill="#EF4444"
                                aria-hidden="true"
                            >
                                <path d="M12 0C5.37 0 0 5.37 0 12c0 9 12 20 12 20s12-11 12-20c0-6.63-5.37-12-12-12zm0 16c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4z" />
                            </svg>
                            <span className="text-[10px] text-red-600 font-bold mt-0.5 bg-white/80 px-1 rounded">
                                {locationDisplay}
                            </span>
                        </div>

                        {/* Path line */}
                        <svg
                            className="absolute inset-0 w-full h-full"
                            aria-hidden="true"
                        >
                            <line
                                x1="28%"
                                y1="68%"
                                x2="72%"
                                y2="30%"
                                stroke="#EF4444"
                                strokeWidth="2"
                                strokeDasharray="6 4"
                                opacity="0.6"
                            />
                        </svg>
                    </div>
                </div>
            </div>

            {/* Bottom Info Card */}
            <div className="bg-white border-t border-gray-100 px-5 py-4">
                {/* Product Info */}
                <div className="flex items-center gap-3 mb-3">
                    <div className="w-10 h-10 bg-gray-100 rounded-lg flex items-center justify-center flex-shrink-0">
                        <svg
                            width="20"
                            height="20"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="#9CA3AF"
                            strokeWidth="1.5"
                            aria-hidden="true"
                        >
                            <rect x="3" y="3" width="18" height="18" rx="2" />
                            <circle cx="8.5" cy="8.5" r="1.5" />
                            <polyline points="21 15 16 10 5 21" />
                        </svg>
                    </div>
                    <div>
                        <h2 className="text-sm font-bold text-gray-900">
                            {product}
                        </h2>
                        <div className="flex items-center gap-1 text-xs text-red-500 font-medium mt-0.5">
                            <svg
                                width="10"
                                height="10"
                                viewBox="0 0 24 24"
                                fill="currentColor"
                                aria-hidden="true"
                            >
                                <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
                            </svg>
                            {location}
                        </div>
                    </div>
                </div>

                {/* Distance & Time */}
                <div className="flex items-center justify-between mb-4 px-1">
                    <div>
                        <p className="text-[10px] text-gray-400 uppercase tracking-wide">
                            남은 거리
                        </p>
                        <p className="text-lg font-bold text-gray-900">
                            약 15m
                        </p>
                    </div>
                    <div className="text-right">
                        <p className="text-[10px] text-gray-400 uppercase tracking-wide">
                            예상 시간
                        </p>
                        <p className="text-lg font-bold text-gray-900">
                            20초
                        </p>
                    </div>
                </div>

                {/* Arrival Button */}
                <button
                    onClick={handleArrived}
                    className="w-full flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-red-600 text-white font-bold text-base cursor-pointer transition-all duration-200 hover:bg-red-700 active:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
                >
                    <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                    >
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                        <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                    도착 완료
                </button>
            </div>
        </main>
    );
}

export default function MobileMapPage() {
    return (
        <Suspense
            fallback={
                <main className="flex min-h-screen items-center justify-center bg-white max-w-md mx-auto">
                    <div className="w-12 h-12 border-4 border-red-400 border-t-transparent rounded-full animate-spin" />
                </main>
            }
        >
            <MobileMapContent />
        </Suspense>
    );
}
