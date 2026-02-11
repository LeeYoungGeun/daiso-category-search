"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

export default function MobileScanPage() {
    const router = useRouter();
    const [manualInput, setManualInput] = useState("");
    const [showManualInput, setShowManualInput] = useState(false);

    const handleScanComplete = useCallback(
        (url?: string) => {
            // Parse QR URL or use default demo data
            if (url) {
                try {
                    const parsed = new URL(url);
                    const params = parsed.searchParams;
                    const product = params.get("product") || "";
                    const location = params.get("location") || "";
                    const productId = params.get("product_id") || "";
                    router.push(
                        `/mobile/map?product=${encodeURIComponent(product)}&location=${encodeURIComponent(location)}&product_id=${encodeURIComponent(productId)}`
                    );
                    return;
                } catch {
                    // Not a valid URL, try as product name
                }
            }

            // Demo: navigate with sample data
            router.push(
                "/mobile/map?product=퍼실 파워젤 세탁세제&location=생활용품 > 세탁세제"
            );
        },
        [router]
    );

    const handleManualSearch = useCallback(() => {
        if (!manualInput.trim()) return;
        // Treat manual input as a product search URL
        router.push(
            `/mobile/map?product=${encodeURIComponent(manualInput)}&location=매장 내`
        );
    }, [manualInput, router]);

    return (
        <main className="flex min-h-screen flex-col bg-black text-white max-w-md mx-auto">
            {/* Status Bar Placeholder */}
            <div className="flex items-center justify-between px-5 py-2 text-xs">
                <span className="font-medium">
                    {new Date().getHours().toString().padStart(2, "0")}:
                    {new Date().getMinutes().toString().padStart(2, "0")}
                </span>
                <div className="flex items-center gap-1">
                    <svg
                        width="16"
                        height="12"
                        viewBox="0 0 16 12"
                        fill="white"
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
                        fill="white"
                        aria-hidden="true"
                    >
                        <rect
                            x="1"
                            y="4"
                            width="20"
                            height="10"
                            rx="2"
                            stroke="white"
                            strokeWidth="1.5"
                            fill="none"
                        />
                        <rect x="22" y="7" width="2" height="4" rx="0.5" />
                        <rect x="3" y="6" width="14" height="6" rx="1" fill="white" />
                    </svg>
                </div>
            </div>

            {/* Header */}
            <header className="px-5 py-3">
                <h1 className="text-lg font-bold">다이소 위치 안내</h1>
            </header>

            {/* Camera / QR Scanner Area */}
            <div className="flex-1 flex flex-col items-center justify-center px-6 relative">
                {/* Scanner Frame */}
                <div
                    className="w-full aspect-square max-w-[280px] relative mb-8"
                    role="img"
                    aria-label="QR 코드 스캐너"
                >
                    {/* Corner brackets */}
                    <div className="absolute top-0 left-0 w-10 h-10 border-t-2 border-l-2 border-white/60 rounded-tl-lg" />
                    <div className="absolute top-0 right-0 w-10 h-10 border-t-2 border-r-2 border-white/60 rounded-tr-lg" />
                    <div className="absolute bottom-0 left-0 w-10 h-10 border-b-2 border-l-2 border-white/60 rounded-bl-lg" />
                    <div className="absolute bottom-0 right-0 w-10 h-10 border-b-2 border-r-2 border-white/60 rounded-br-lg" />

                    {/* Scan line animation */}
                    <div className="absolute inset-x-4 top-1/2 h-0.5 bg-red-500/80 animate-pulse" />
                </div>

                {/* Instruction Text */}
                <p className="text-sm text-gray-400 text-center">
                    키오스크의 QR 코드를 스캔해주세요
                </p>

                {/* Demo: Simulate scan button */}
                <button
                    onClick={() => handleScanComplete()}
                    className="mt-8 px-6 py-3 bg-white/10 rounded-lg text-sm text-white/70 hover:bg-white/20 cursor-pointer transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white/40"
                >
                    (데모) 스캔 시뮬레이션
                </button>

                {/* Manual URL Input Toggle */}
                <button
                    onClick={() => setShowManualInput(!showManualInput)}
                    className="mt-4 text-xs text-gray-500 hover:text-gray-300 cursor-pointer transition-colors"
                >
                    {showManualInput ? "닫기" : "직접 입력하기"}
                </button>

                {/* Manual Input */}
                {showManualInput && (
                    <div className="mt-3 w-full max-w-[280px] flex gap-2">
                        <input
                            type="text"
                            value={manualInput}
                            onChange={(e) => setManualInput(e.target.value)}
                            onKeyDown={(e) =>
                                e.key === "Enter" && handleManualSearch()
                            }
                            placeholder="상품명 또는 QR URL"
                            className="flex-1 px-3 py-2 bg-white/10 rounded-lg text-sm text-white placeholder-gray-500 outline-none focus:ring-2 focus:ring-white/30"
                        />
                        <button
                            onClick={handleManualSearch}
                            className="px-4 py-2 bg-red-600 rounded-lg text-sm text-white hover:bg-red-700 cursor-pointer transition-colors"
                        >
                            이동
                        </button>
                    </div>
                )}
            </div>

            {/* Bottom Controls */}
            <div className="flex items-center justify-center gap-8 px-6 py-6 border-t border-white/10">
                <button
                    className="flex flex-col items-center gap-1 text-gray-400 hover:text-white cursor-pointer transition-colors duration-200 focus:outline-none"
                    aria-label="플래시 켜기"
                >
                    <svg
                        width="24"
                        height="24"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                    >
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                    </svg>
                    <span className="text-xs">플래시</span>
                </button>
                <button
                    className="flex flex-col items-center gap-1 text-gray-400 hover:text-white cursor-pointer transition-colors duration-200 focus:outline-none"
                    aria-label="갤러리에서 QR 코드 선택"
                >
                    <svg
                        width="24"
                        height="24"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                    >
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                    </svg>
                    <span className="text-xs">갤러리</span>
                </button>
            </div>
        </main>
    );
}
