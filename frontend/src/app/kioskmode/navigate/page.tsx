"use client";

import { useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function NavigateContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const location = searchParams.get("location") || "매장 내";
    const product = searchParams.get("product") || "";
    const productId = searchParams.get("product_id") || "";
    const price = searchParams.get("price") || "";
    const qrPayload = searchParams.get("qr") || "";
    const walkTime = searchParams.get("time") || "약 30초";

    const handleBack = useCallback(() => {
        router.back();
    }, [router]);

    const handleGoHome = useCallback(() => {
        router.push("/kioskmode");
    }, [router]);

    const handleMobileGuide = useCallback(() => {
        // Build mobile URL with product info for QR code
        const mobileParams = new URLSearchParams({
            product: product,
            location: location,
            product_id: productId,
        });
        const mobileUrl = `${window.location.origin}/mobile/map?${mobileParams.toString()}`;

        // Copy to clipboard as fallback
        navigator.clipboard?.writeText(mobileUrl).catch(() => {});

        alert(
            `모바일 안내 URL이 생성되었습니다.\n\n${mobileUrl}\n\n실제 서비스에서는 QR 코드가 표시됩니다.`
        );
    }, [product, location, productId]);

    return (
        <main className="flex min-h-screen flex-col bg-gray-50">
            {/* Header */}
            <header className="w-full bg-white px-6 py-4 border-b border-gray-100">
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

            {/* Content */}
            <div className="flex-1 px-4 sm:px-6 py-6">
                <div className="max-w-5xl mx-auto flex flex-col lg:flex-row gap-6">
                    {/* Left: Store Map */}
                    <div className="flex-1">
                        <article className="bg-white rounded-2xl shadow-sm p-6 h-full">
                            <h2 className="text-lg font-bold text-gray-900 mb-4 text-center">
                                매장 지도
                            </h2>

                            {/* Map Placeholder */}
                            <div
                                className="w-full aspect-[4/3] bg-gray-50 rounded-xl border-2 border-dashed border-gray-200 flex items-center justify-center mb-6"
                                role="img"
                                aria-label={`매장 지도 - 현재 위치에서 ${location}까지의 경로`}
                            >
                                {/* Placeholder map visualization */}
                                <div className="text-center">
                                    <svg
                                        width="64"
                                        height="64"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        stroke="#D1D5DB"
                                        strokeWidth="1"
                                        className="mx-auto mb-3"
                                        aria-hidden="true"
                                    >
                                        <rect x="3" y="3" width="18" height="18" rx="2" />
                                        <path d="M3 9h18" />
                                        <path d="M9 3v18" />
                                        <circle cx="6" cy="15" r="1.5" fill="#3B82F6" stroke="none" />
                                        <circle cx="15" cy="6" r="1.5" fill="#EF4444" stroke="none" />
                                        <path
                                            d="M6 15 L9 12 L12 9 L15 6"
                                            stroke="#EF4444"
                                            strokeWidth="1.5"
                                            strokeDasharray="3 2"
                                        />
                                    </svg>
                                    <p className="text-sm text-gray-400">
                                        매장 지도가 여기에 표시됩니다
                                    </p>
                                </div>
                            </div>

                            {/* Legend */}
                            <div className="flex items-center justify-center gap-6">
                                <div className="flex items-center gap-2">
                                    <span
                                        className="w-3 h-3 rounded-full bg-blue-500 inline-block"
                                        aria-hidden="true"
                                    />
                                    <span className="text-sm text-gray-600">
                                        현재 위치
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <span
                                        className="w-3 h-3 rounded-full bg-red-500 inline-block"
                                        aria-hidden="true"
                                    />
                                    <span className="text-sm text-gray-600">
                                        {location}
                                    </span>
                                </div>
                            </div>
                        </article>
                    </div>

                    {/* Right: Navigation Info */}
                    <div className="lg:w-80">
                        <div className="bg-white rounded-2xl shadow-sm p-6 flex flex-col items-center">
                            {/* Location Title */}
                            <div className="flex items-center gap-2 mb-2">
                                <svg
                                    width="24"
                                    height="24"
                                    viewBox="0 0 24 24"
                                    fill="#EF4444"
                                    aria-hidden="true"
                                >
                                    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
                                </svg>
                                <h2 className="text-xl sm:text-2xl font-bold text-gray-900">
                                    {location}
                                </h2>
                            </div>

                            {/* Product Name */}
                            {product && (
                                <p className="text-sm text-gray-500 mb-1">
                                    {product}
                                </p>
                            )}

                            {/* Price */}
                            {price && (
                                <p className="text-lg font-bold text-red-600 mb-2">
                                    ₩{Number(price).toLocaleString()}
                                </p>
                            )}

                            {/* Walk Time */}
                            <p className="text-sm text-gray-500 mb-6">
                                예상 도보 시간: {walkTime}
                            </p>

                            {/* QR Code */}
                            <div
                                className="w-48 h-48 sm:w-56 sm:h-56 bg-gray-100 rounded-xl flex items-center justify-center mb-4"
                                role="img"
                                aria-label="QR 코드 - 스마트폰으로 스캔하여 지도 안내 받기"
                            >
                                {/* QR Code Placeholder - SVG pattern */}
                                <svg
                                    width="160"
                                    height="160"
                                    viewBox="0 0 160 160"
                                    aria-hidden="true"
                                >
                                    {/* Top-left finder pattern */}
                                    <rect x="10" y="10" width="40" height="40" fill="#111" rx="2" />
                                    <rect x="15" y="15" width="30" height="30" fill="white" rx="1" />
                                    <rect x="20" y="20" width="20" height="20" fill="#111" rx="1" />

                                    {/* Top-right finder pattern */}
                                    <rect x="110" y="10" width="40" height="40" fill="#111" rx="2" />
                                    <rect x="115" y="15" width="30" height="30" fill="white" rx="1" />
                                    <rect x="120" y="20" width="20" height="20" fill="#111" rx="1" />

                                    {/* Bottom-left finder pattern */}
                                    <rect x="10" y="110" width="40" height="40" fill="#111" rx="2" />
                                    <rect x="15" y="115" width="30" height="30" fill="white" rx="1" />
                                    <rect x="20" y="120" width="20" height="20" fill="#111" rx="1" />

                                    {/* Data modules (simplified) */}
                                    <rect x="60" y="10" width="8" height="8" fill="#111" />
                                    <rect x="76" y="10" width="8" height="8" fill="#111" />
                                    <rect x="92" y="10" width="8" height="8" fill="#111" />
                                    <rect x="60" y="26" width="8" height="8" fill="#111" />
                                    <rect x="76" y="26" width="8" height="8" fill="#111" />
                                    <rect x="60" y="42" width="8" height="8" fill="#111" />
                                    <rect x="92" y="42" width="8" height="8" fill="#111" />

                                    <rect x="10" y="60" width="8" height="8" fill="#111" />
                                    <rect x="26" y="60" width="8" height="8" fill="#111" />
                                    <rect x="42" y="60" width="8" height="8" fill="#111" />
                                    <rect x="60" y="60" width="8" height="8" fill="#111" />
                                    <rect x="76" y="60" width="8" height="8" fill="#111" />
                                    <rect x="92" y="60" width="8" height="8" fill="#111" />
                                    <rect x="110" y="60" width="8" height="8" fill="#111" />
                                    <rect x="126" y="60" width="8" height="8" fill="#111" />
                                    <rect x="142" y="60" width="8" height="8" fill="#111" />

                                    <rect x="10" y="76" width="8" height="8" fill="#111" />
                                    <rect x="42" y="76" width="8" height="8" fill="#111" />
                                    <rect x="60" y="76" width="8" height="8" fill="#111" />
                                    <rect x="92" y="76" width="8" height="8" fill="#111" />
                                    <rect x="110" y="76" width="8" height="8" fill="#111" />
                                    <rect x="142" y="76" width="8" height="8" fill="#111" />

                                    <rect x="10" y="92" width="8" height="8" fill="#111" />
                                    <rect x="26" y="92" width="8" height="8" fill="#111" />
                                    <rect x="42" y="92" width="8" height="8" fill="#111" />
                                    <rect x="76" y="92" width="8" height="8" fill="#111" />
                                    <rect x="110" y="92" width="8" height="8" fill="#111" />
                                    <rect x="126" y="92" width="8" height="8" fill="#111" />
                                    <rect x="142" y="92" width="8" height="8" fill="#111" />

                                    <rect x="60" y="110" width="8" height="8" fill="#111" />
                                    <rect x="76" y="110" width="8" height="8" fill="#111" />
                                    <rect x="92" y="110" width="8" height="8" fill="#111" />
                                    <rect x="110" y="110" width="8" height="8" fill="#111" />
                                    <rect x="142" y="110" width="8" height="8" fill="#111" />

                                    <rect x="60" y="126" width="8" height="8" fill="#111" />
                                    <rect x="92" y="126" width="8" height="8" fill="#111" />
                                    <rect x="126" y="126" width="8" height="8" fill="#111" />

                                    <rect x="60" y="142" width="8" height="8" fill="#111" />
                                    <rect x="76" y="142" width="8" height="8" fill="#111" />
                                    <rect x="110" y="142" width="8" height="8" fill="#111" />
                                    <rect x="142" y="142" width="8" height="8" fill="#111" />
                                </svg>
                            </div>

                            {/* QR Info Text */}
                            <div className="bg-red-50 rounded-lg px-4 py-3 mb-6 w-full">
                                <p className="text-xs sm:text-sm text-red-600 text-center leading-relaxed">
                                    <svg
                                        width="14"
                                        height="14"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        stroke="currentColor"
                                        strokeWidth="2"
                                        className="inline-block mr-1 -mt-0.5"
                                        aria-hidden="true"
                                    >
                                        <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
                                        <line x1="12" y1="18" x2="12.01" y2="18" />
                                    </svg>
                                    QR 코드를 스캔하면 스마트폰으로 지도를 보며 이동할 수 있어요!
                                </p>
                            </div>

                            {/* Action Buttons */}
                            <div className="flex items-center gap-3 w-full">
                                <button
                                    onClick={handleGoHome}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 border-gray-300 text-gray-700 font-medium cursor-pointer transition-all duration-200 hover:bg-gray-50 hover:border-gray-400 active:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
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
                                        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                                        <polyline points="9 22 9 12 15 12 15 22" />
                                    </svg>
                                    처음으로
                                </button>
                                <button
                                    onClick={handleMobileGuide}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-red-600 text-white font-medium cursor-pointer transition-all duration-200 hover:bg-red-700 active:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
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
                                        <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
                                        <line x1="12" y1="18" x2="12.01" y2="18" />
                                    </svg>
                                    모바일로 안내받기
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    );
}

export default function NavigatePage() {
    return (
        <Suspense
            fallback={
                <main className="flex min-h-screen items-center justify-center bg-gray-50">
                    <div className="w-12 h-12 border-4 border-red-400 border-t-transparent rounded-full animate-spin" />
                </main>
            }
        >
            <NavigateContent />
        </Suspense>
    );
}
