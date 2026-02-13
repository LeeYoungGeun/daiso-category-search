#!/usr/bin/env python3
"""
Quick /v1/search load test for Lightsail deployment readiness.
Reuses TokenBucketLimiter from loadtest_rerank.py.

Usage:
    python scripts/loadtest_search.py
    python scripts/loadtest_search.py --vus 5 --duration 10
    python scripts/loadtest_search.py --vus 3 --duration 30 --target-qpm 30 --rollup-sec 10
"""

import argparse
import asyncio
import random
import statistics
import time
from typing import List, Optional

import httpx

# ── Search queries (realistic Korean product searches) ───────────────────────
QUERIES = [
    "물티슈",
    "칫솔",
    "주방 세제",
    "파란색 볼펜",
    "겨울에 창문에 붙이는 뽁뽁이",
    "튀김 건질 때 쓰는 거",
    "아이폰 충전기",
    "욕실 매트",
    "빨래 건조대",
    "수납 박스",
    "화장지",
    "면봉",
    "고무장갑",
    "쓰레기봉투",
    "행주",
]


# ── Token bucket (simplified inline) ────────────────────────────────────────
class TokenBucket:
    def __init__(self, qpm: int = 0):
        self._interval = 60.0 / qpm if qpm > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next: float = 0.0

    async def acquire(self):
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                wait = self._next - now
                self._next += self._interval
            else:
                wait = 0.0
                self._next = now + self._interval
        if wait > 0:
            await asyncio.sleep(wait)


def percentile(data: List[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = min(int(len(s) * pct / 100), len(s) - 1)
    return s[idx]


async def worker(
    client: httpx.AsyncClient,
    url: str,
    latencies: List[float],
    errors: List[str],
    stop: asyncio.Event,
    bucket: Optional[TokenBucket],
):
    while not stop.is_set():
        if bucket:
            await bucket.acquire()
            if stop.is_set():
                break
        query = random.choice(QUERIES)
        payload = {"query": query}
        t0 = time.perf_counter()
        try:
            resp = await client.post(url, json=payload, timeout=15.0)
            ms = (time.perf_counter() - t0) * 1000
            latencies.append(ms)
            if resp.status_code != 200:
                errors.append(f"HTTP {resp.status_code}")
            else:
                body = resp.json()
                if body.get("error"):
                    errors.append(f"app_error: {body['error'][:60]}")
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            latencies.append(ms)
            errors.append(str(e)[:80])
        await asyncio.sleep(0.01)


async def run(base_url: str, vus: int, duration: int, target_qpm: int, rollup_sec: int):
    url = f"{base_url}/v1/search"
    latencies: List[float] = []
    errors: List[str] = []
    stop_event = asyncio.Event()
    bucket = TokenBucket(target_qpm) if target_qpm > 0 else None

    qpm_label = str(target_qpm) if target_qpm > 0 else "unlimited"
    print(f"\n[START] /v1/search load test: {vus} VUs, {duration}s, target QPM={qpm_label}")
    print(f"   URL: {url}")
    if rollup_sec > 0:
        print(f"   Rollup every {rollup_sec}s")
    print()

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(worker(client, url, latencies, errors, stop_event, bucket))
            for _ in range(vus)
        ]

        if rollup_sec > 0:
            remaining = duration
            elapsed = 0
            while remaining > 0:
                interval = min(rollup_sec, remaining)
                snap_lat = len(latencies)
                snap_err = len(errors)
                await asyncio.sleep(interval)
                remaining -= interval
                elapsed += interval
                iv_lats = latencies[snap_lat:]
                iv_errs = errors[snap_err:]
                iv_p95 = percentile(iv_lats, 95)
                iv_reqs = len(iv_lats)
                iv_err_count = len(iv_errs)
                iv_err_rate = (iv_err_count / iv_reqs * 100) if iv_reqs > 0 else 0
                iv_qpm = int(iv_reqs / interval * 60) if interval > 0 else 0
                print(
                    f"[ROLLUP t={elapsed:>4}s] reqs={iv_reqs:>5}, "
                    f"errors={iv_err_count:>3} ({iv_err_rate:.1f}%), "
                    f"p95={iv_p95:>8.1f}ms, qpm={iv_qpm:>5}"
                )
        else:
            await asyncio.sleep(duration)

        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Results
    total = len(latencies)
    err_count = len(errors)
    err_rate = (err_count / total * 100) if total > 0 else 0
    qpm = int(total / duration * 60) if duration > 0 else 0
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    avg = statistics.mean(latencies) if latencies else 0

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║          /v1/search Load Test Results                ║")
    print("╠══════════════════════════════════════════════════════╣")
    print(f"║  Virtual Users  : {vus:>8}                         ║")
    print(f"║  Duration (sec) : {duration:>8}                         ║")
    print(f"║  Target QPM     : {qpm_label:>8}                         ║")
    print(f"║  Total Requests : {total:>8}                         ║")
    print(f"║  QPM (actual)   : {qpm:>8}                         ║")
    print(f"║  Errors         : {err_count:>8} ({err_rate:.1f}%)               ║")
    print(f"║  Avg latency    : {avg:>8.1f}ms                       ║")
    print(f"║  p50 latency    : {p50:>8.1f}ms                       ║")
    print(f"║  p95 latency    : {p95:>8.1f}ms                       ║")
    print(f"║  p99 latency    : {p99:>8.1f}ms                       ║")
    print("╚══════════════════════════════════════════════════════╝")

    if err_count > 0:
        unique = set(errors[:10])
        print(f"\n[WARN] Sample errors: {unique}")

    return {"total": total, "qpm": qpm, "errors": err_count, "p50": p50, "p95": p95, "p99": p99, "avg": avg}


def main():
    parser = argparse.ArgumentParser(description="/v1/search Load Test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--vus", type=int, default=3)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--target-qpm", type=int, default=0)
    parser.add_argument("--rollup-sec", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.vus, args.duration, args.target_qpm, args.rollup_sec))


if __name__ == "__main__":
    main()
