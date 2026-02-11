#!/usr/bin/env python3
"""
Python Load Test — /ml/rerank QPM Measurement

No external dependencies beyond httpx (already installed).

Usage:
    python scripts/loadtest_rerank.py
    python scripts/loadtest_rerank.py --vus 10 --duration 30
    python scripts/loadtest_rerank.py --base-url http://localhost:8000

Output:
    Total requests, QPM, p50/p95/p99 latency, error rate
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from typing import List

import httpx

# ── Test payloads ────────────────────────────────────────────────────────────
PAYLOADS = [
    {
        "query": "튀김 건질 때 쓰는 거",
        "candidates": [
            {"id": "1", "name": "스텐 채반", "desc": "튀김/면 요리용 채반"},
            {"id": "2", "name": "세탁망 원형", "desc": "세탁기용 망"},
            {"id": "3", "name": "튀김가루 1kg", "desc": "식재료"},
        ],
    },
    {
        "query": "파란색 볼펜",
        "candidates": [
            {"id": "10", "name": "모나미 볼펜 파랑", "desc": "필기구"},
            {"id": "11", "name": "빨간 볼펜", "desc": "필기구"},
        ],
    },
    {
        "query": "겨울에 창문에 붙이는 뽁뽁이",
        "candidates": [
            {"id": "20", "name": "단열 시트 에어캡", "desc": "창문 단열용"},
            {"id": "21", "name": "장난감 뽁뽁이", "desc": "스트레스 해소"},
        ],
    },
    {
        "query": "주방 세제",
        "candidates": [
            {"id": "30", "name": "퐁퐁 주방세제", "desc": "설거지용"},
            {"id": "31", "name": "세탁 세제", "desc": "세탁기용"},
            {"id": "32", "name": "욕실 세정제", "desc": "욕실 청소용"},
        ],
    },
    {
        "query": "아이폰 충전기",
        "candidates": [
            {"id": "40", "name": "건전지 AA 2개입", "desc": "배터리"},
            {"id": "41", "name": "갤럭시 C타입 케이블", "desc": "삼성 호환"},
        ],
    },
]


async def worker(
    client: httpx.AsyncClient,
    url: str,
    duration: float,
    latencies: List[float],
    errors: List[str],
    stop_event: asyncio.Event,
):
    """Single virtual user sending requests until stop_event is set."""
    while not stop_event.is_set():
        payload = random.choice(PAYLOADS)
        start = time.perf_counter()
        try:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

            if resp.status_code != 200:
                errors.append(f"HTTP {resp.status_code}")
            else:
                body = resp.json()
                if "selected_id" not in body:
                    errors.append("missing selected_id")
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
            errors.append(str(exc))

        # Small sleep to avoid pure CPU spin
        await asyncio.sleep(0.01)


def percentile(data: List[float], pct: float) -> float:
    """Calculate percentile from sorted data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


async def run_load_test(base_url: str, vus: int, duration: int):
    """Run the load test with given parameters."""
    url = f"{base_url}/ml/rerank"
    latencies: List[float] = []
    errors: List[str] = []
    stop_event = asyncio.Event()

    print(f"\n[START] Load test: {vus} VUs, {duration}s, target: {url}")
    print(f"   RERANK_MODE should be 'mock' for pure QPM measurement\n")

    async with httpx.AsyncClient() as client:
        # Start workers
        tasks = [
            asyncio.create_task(
                worker(client, url, duration, latencies, errors, stop_event)
            )
            for _ in range(vus)
        ]

        # Wait for duration
        await asyncio.sleep(duration)
        stop_event.set()

        # Wait for all workers to finish
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── Results ──────────────────────────────────────────────────────────
    total = len(latencies)
    error_count = len(errors)
    error_rate = (error_count / total * 100) if total > 0 else 0
    qpm = int(total / duration * 60) if duration > 0 else 0

    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    avg = statistics.mean(latencies) if latencies else 0

    print("╔══════════════════════════════════════════════════════╗")
    print("║           ML Rerank QPM Load Test Results            ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Virtual Users  : {vus:>8}                         ║")
    print(f"║  Duration (sec) : {duration:>8}                         ║")
    print(f"║  Total Requests : {total:>8}                         ║")
    print(f"║  QPM (est.)     : {qpm:>8}                         ║")
    print(f"║  Errors         : {error_count:>8} ({error_rate:.1f}%)               ║")
    print(f"║  Avg latency    : {avg:>8.1f}ms                       ║")
    print(f"║  p50 latency    : {p50:>8.1f}ms                       ║")
    print(f"║  p95 latency    : {p95:>8.1f}ms                       ║")
    print(f"║  p99 latency    : {p99:>8.1f}ms                       ║")
    print("╚══════════════════════════════════════════════════════╝")

    if error_count > 0:
        unique_errors = set(errors[:10])
        print(f"\n[WARN] Sample errors: {unique_errors}")

    return {
        "total": total,
        "qpm": qpm,
        "errors": error_count,
        "error_rate": error_rate,
        "avg_ms": avg,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
    }


def main():
    parser = argparse.ArgumentParser(description="ML Rerank QPM Load Test")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="Target server URL"
    )
    parser.add_argument("--vus", type=int, default=5, help="Virtual users (concurrency)")
    parser.add_argument("--duration", type=int, default=10, help="Test duration in seconds")
    args = parser.parse_args()

    asyncio.run(run_load_test(args.base_url, args.vus, args.duration))


if __name__ == "__main__":
    main()
