"use client";

import { useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function MobileArrivedContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const product = searchParams.get("product") || "상품";
    const location = searchParams.get("location") || "매장 내";
    const productId = searchParams.get("product_id") || "";

    const handleConfirm = useCallback(() => {
        // Log confirmation (could send to backend analytics)
        console.log("Product found confirmed:", {
            product,
            location,
            productId,
        });
        router.push("/mobile");
    }, [router, product, location, productId]);

    const handleCallStaff = useCallback(() => {
        alert("직원을 호출했습니다. 잠시만 기다려주세요.");
    }, []);

    const handleSearchAgain = useCallback(() => {
        router.push("/mobile");
    }, [router]);

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

            {/* Main Content */}
            <div className="flex-1 flex flex-col items-center justify-center px-6">
                {/* Success Icon */}
                <div className="w-20 h-20 bg-green-50 rounded-full flex items-center justify-center mb-8">
                    <svg
                        width="40"
                        height="40"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="#22C55E"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                    >
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                        <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                </div>

                {/* Title */}
                <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-4 text-center">
                    목적지에 도착했습니다!
                </h1>

                {/* Location */}
                <div className="flex items-center gap-1.5 text-red-500 font-bold text-lg mb-2">
                    <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        aria-hidden="true"
                    >
                        <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
                    </svg>
                    {location}
                </div>

                {/* Product Name */}
                <p className="text-sm text-gray-500 mb-6">{product}</p>

                {/* Question */}
                <p className="text-sm text-gray-600 mb-8">
                    찾으시는 상품이 맞으신가요?
                </p>

                {/* Action Buttons */}
                <div className="w-full max-w-xs flex flex-col gap-3">
                    <button
                        onClick={handleConfirm}
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
                            <circle cx="12" cy="12" r="10" />
                            <path d="M8 14s1.5 2 4 2 4-2 4-2" />
                            <line x1="9" y1="9" x2="9.01" y2="9" />
                            <line x1="15" y1="9" x2="15.01" y2="9" />
                        </svg>
                        네, 맞아요!
                    </button>
                    <button
                        onClick={handleCallStaff}
                        className="w-full flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl border-2 border-gray-200 text-gray-700 font-medium text-base cursor-pointer transition-all duration-200 hover:bg-gray-50 hover:border-gray-300 active:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
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
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                            <circle cx="12" cy="7" r="4" />
                        </svg>
                        직원 호출
                    </button>
                    <button
                        onClick={handleSearchAgain}
                        className="w-full flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-gray-500 font-medium text-sm cursor-pointer transition-all duration-200 hover:text-gray-700 focus:outline-none"
                    >
                        다른 상품 찾기
                    </button>
                </div>
            </div>
        </main>
    );
}

export default function MobileArrivedPage() {
    return (
        <Suspense
            fallback={
                <main className="flex min-h-screen items-center justify-center bg-white max-w-md mx-auto">
                    <div className="w-12 h-12 border-4 border-red-400 border-t-transparent rounded-full animate-spin" />
                </main>
            }
        >
            <MobileArrivedContent />
        </Suspense>
    );
}
