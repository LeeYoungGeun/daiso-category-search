#!/usr/bin/env python3
"""
Python Load Test — /ml/rerank QPM Measurement

No external dependencies beyond httpx (already installed).

Usage:
    python scripts/loadtest_rerank.py
    python scripts/loadtest_rerank.py --vus 10 --duration 30
    python scripts/loadtest_rerank.py --base-url http://localhost:8000
    python scripts/loadtest_rerank.py --vus 10 --duration 600 --target-qpm 400
    python scripts/loadtest_rerank.py --vus 10 --steps "400:30,1200:60"
    python scripts/loadtest_rerank.py --vus 10 --steps "400:60,800:60,1200:60,2000:60" \
        --stop-on-error-rate 0.05 --stop-on-p95-ms 1500
    python scripts/loadtest_rerank.py --vus 10 --duration 1800 --target-qpm 300 --rollup-sec 60
    python scripts/loadtest_rerank.py --mode simulated --sim-timeout-rate 0.01 \
        --sim-latency-ms 300 --sim-jitter-ms 150 --vus 5 --duration 60

Output:
    Total requests, QPM, p50/p95/p99 latency, error rate
    (with --rollup-sec: periodic 1-line summaries every N seconds)
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from typing import Dict, List, Optional, Tuple

import httpx

# ── Vendor env force/restore helpers ─────────────────────────────────────────
_VENDOR_ENV_KEYS = ["VENDOR_ENABLED", "VENDOR_SAMPLE_RATE", "VENDOR_MAX_CALLS_PER_MIN"]
_saved_env: Dict[str, Optional[str]] = {}


def _force_vendor_off() -> None:
    """Force vendor-related env vars OFF and save originals for later restore."""
    overrides = {
        "VENDOR_ENABLED": "false",
        "VENDOR_SAMPLE_RATE": "0",
        "VENDOR_MAX_CALLS_PER_MIN": "0",
    }
    for key, forced_val in overrides.items():
        _saved_env[key] = os.environ.get(key)  # None if absent
        os.environ[key] = forced_val

    # Warn if RERANK_MODE looks like it might hit a real vendor
    rerank_mode = os.environ.get("RERANK_MODE", "")
    if rerank_mode and rerank_mode not in ("mock", "rule", ""):
        print(
            f"[WARN] RERANK_MODE={rerank_mode!r} is set — vendor calls may still "
            "occur server-side. Consider using RERANK_MODE=mock for load tests."
        )

    print("[INFO] Vendor env forced OFF for load test:")
    for key in _VENDOR_ENV_KEYS:
        print(f"       {key}={os.environ.get(key)}")


def _restore_env() -> None:
    """Restore all saved env vars to their original values (or unset if absent)."""
    for key in list(_saved_env.keys()):
        original = _saved_env.get(key)
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original
    print("[INFO] Env vars restored to original values.")


# ── Mode / simulation env helpers ────────────────────────────────────────────
_SIM_ENV_KEYS = [
    "RERANK_MODE",
    "SIM_TIMEOUT_RATE",
    "SIM_RATE_LIMIT_RATE",
    "SIM_LATENCY_MS",
    "SIM_JITTER_MS",
]


def _force_mode_env(
    mode: str,
    sim_timeout_rate: Optional[float] = None,
    sim_rate_limit_rate: Optional[float] = None,
    sim_latency_ms: Optional[int] = None,
    sim_jitter_ms: Optional[int] = None,
) -> None:
    """Force RERANK_MODE and SIM_* env vars, saving originals for restore.

    VENDOR_* OFF vars are NOT touched here (handled by _force_vendor_off).
    """
    # Save originals for all SIM keys
    for key in _SIM_ENV_KEYS:
        if key not in _saved_env:
            _saved_env[key] = os.environ.get(key)

    # Set RERANK_MODE
    os.environ["RERANK_MODE"] = mode
    print(f"[INFO] RERANK_MODE forced to {mode!r}")

    # Set SIM_* vars only when provided
    sim_overrides: Dict[str, str] = {}
    if sim_timeout_rate is not None:
        sim_overrides["SIM_TIMEOUT_RATE"] = str(sim_timeout_rate)
    if sim_rate_limit_rate is not None:
        sim_overrides["SIM_RATE_LIMIT_RATE"] = str(sim_rate_limit_rate)
    if sim_latency_ms is not None:
        sim_overrides["SIM_LATENCY_MS"] = str(sim_latency_ms)
    if sim_jitter_ms is not None:
        sim_overrides["SIM_JITTER_MS"] = str(sim_jitter_ms)

    for key, val in sim_overrides.items():
        os.environ[key] = val

    if sim_overrides:
        print("[INFO] Simulation env vars set:")
        for key, val in sim_overrides.items():
            print(f"       {key}={val}")

# ── Steps parser ─────────────────────────────────────────────────────────────

def parse_steps(steps_str: str) -> List[Tuple[int, int]]:
    """Parse a steps string like '400:30,1200:60' into [(qpm, duration_sec), ...].

    Each segment is 'QPM:SECONDS'. Raises ValueError on bad format.
    """
    result: List[Tuple[int, int]] = []
    for segment in steps_str.split(","):
        segment = segment.strip()
        if not segment:
            continue
        parts = segment.split(":")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid step format {segment!r} — expected 'QPM:SECONDS'"
            )
        qpm = int(parts[0].strip())
        dur = int(parts[1].strip())
        if qpm < 0 or dur <= 0:
            raise ValueError(
                f"Invalid step values {segment!r} — QPM >= 0 and SECONDS > 0 required"
            )
        result.append((qpm, dur))
    if not result:
        raise ValueError("Steps string is empty")
    return result


# ── Stop condition checker ───────────────────────────────────────────────────

def should_stop_step(
    *,
    step_errors: int,
    step_total: int,
    step_p95_ms: float,
    max_error_rate: Optional[float] = None,
    max_p95_ms: Optional[float] = None,
) -> Tuple[bool, str]:
    """Check whether the current step exceeds stop thresholds.

    Returns:
        (should_stop, reason) — reason is empty string if should_stop is False.
    """
    if step_total == 0:
        return False, ""

    if max_error_rate is not None:
        actual_rate = step_errors / step_total
        if actual_rate > max_error_rate:
            return True, f"error_rate={actual_rate:.3f} > {max_error_rate}"

    if max_p95_ms is not None and step_p95_ms > max_p95_ms:
        return True, f"p95={step_p95_ms:.1f}ms > {max_p95_ms}ms"

    return False, ""


# ── Token-bucket rate limiter (shared across VUs) ────────────────────────────

class TokenBucketLimiter:
    """Async token-bucket rate limiter shared across all virtual users.

    Args:
        target_qpm: Target queries per minute. 0 means unlimited.
    """

    def __init__(self, target_qpm: int = 0) -> None:
        self.target_qpm = target_qpm
        if target_qpm > 0:
            self._interval = 60.0 / target_qpm  # seconds between tokens
        else:
            self._interval = 0.0
        self._lock = asyncio.Lock()
        self._next_allowed: float = 0.0  # monotonic timestamp

    def update_rate(self, new_qpm: int) -> None:
        """Dynamically change the target QPM (thread-safe via asyncio lock)."""
        self.target_qpm = new_qpm
        if new_qpm > 0:
            self._interval = 60.0 / new_qpm
        else:
            self._interval = 0.0

    async def acquire(self) -> None:
        """Wait until a token is available. No-op when target_qpm == 0."""
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                wait = self._next_allowed - now
                self._next_allowed += self._interval
            else:
                wait = 0.0
                self._next_allowed = now + self._interval
        if wait > 0:
            await asyncio.sleep(wait)


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
    limiter: Optional[TokenBucketLimiter] = None,
):
    """Single virtual user sending requests until stop_event is set."""
    while not stop_event.is_set():
        # Rate-limit if target QPM is set
        if limiter is not None:
            await limiter.acquire()
            if stop_event.is_set():
                break
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
                # ── Vendor trace detection ───────────────────────────
                # Header check: X-Vendor-Called == "1"
                vendor_header = resp.headers.get("X-Vendor-Called", "")
                if vendor_header == "1":
                    errors.append("vendor_called")

                body = resp.json()
                if "selected_id" not in body:
                    errors.append("missing selected_id")

                # Body check: vendor_model or vendor_called keys present
                if "vendor_model" in body or "vendor_called" in body:
                    errors.append("vendor_suspect")
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


def _print_results(
    *,
    vus: int,
    duration: int,
    target_qpm: int,
    latencies: List[float],
    errors: List[str],
    label: str = "ML Rerank QPM Load Test Results",
) -> dict:
    """Compute and print results table. Returns result dict."""
    total = len(latencies)
    error_count = len(errors)
    error_rate = (error_count / total * 100) if total > 0 else 0
    qpm = int(total / duration * 60) if duration > 0 else 0

    vendor_called_count = sum(1 for e in errors if e == "vendor_called")
    vendor_suspect_count = sum(1 for e in errors if e == "vendor_suspect")

    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    avg = statistics.mean(latencies) if latencies else 0

    target_qpm_str = str(target_qpm) if target_qpm > 0 else "unlimited"

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  {label:^52} ║")
    print(f"╠══════════════════════════════════════════════════════╣")
    print(f"║  Virtual Users  : {vus:>8}                         ║")
    print(f"║  Duration (sec) : {duration:>8}                         ║")
    print(f"║  Target QPM     : {target_qpm_str:>8}                         ║")
    print(f"║  Total Requests : {total:>8}                         ║")
    print(f"║  QPM (actual)   : {qpm:>8}                         ║")
    print(f"║  Errors         : {error_count:>8} ({error_rate:.1f}%)               ║")
    print(f"║  vendor_called  : {vendor_called_count:>8}   (should be 0)         ║")
    print(f"║  vendor_suspect : {vendor_suspect_count:>8}   (should be 0)         ║")
    print(f"║  Avg latency    : {avg:>8.1f}ms                       ║")
    print(f"║  p50 latency    : {p50:>8.1f}ms                       ║")
    print(f"║  p95 latency    : {p95:>8.1f}ms                       ║")
    print(f"║  p99 latency    : {p99:>8.1f}ms                       ║")
    print(f"╚══════════════════════════════════════════════════════╝")

    if vendor_called_count > 0 or vendor_suspect_count > 0:
        print("\n[FAIL] Vendor calls detected during load test!")

    if error_count > 0:
        unique_errors = set(errors[:10])
        print(f"\n[WARN] Sample errors: {unique_errors}")

    return {
        "total": total,
        "qpm": qpm,
        "errors": error_count,
        "error_rate": error_rate,
        "vendor_called_count": vendor_called_count,
        "vendor_suspect_count": vendor_suspect_count,
        "avg_ms": avg,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
    }


def _print_rollup(
    *,
    elapsed_sec: int,
    interval_reqs: int,
    interval_errors: int,
    interval_p95: float,
    interval_sec: int,
) -> None:
    """Print a 1-line rollup summary for the most recent interval."""
    err_rate = (interval_errors / interval_reqs * 100) if interval_reqs > 0 else 0.0
    interval_qpm = int(interval_reqs / interval_sec * 60) if interval_sec > 0 else 0
    print(
        f"[ROLLUP t={elapsed_sec:>5}s] "
        f"reqs={interval_reqs:>6}, "
        f"errors={interval_errors:>4} ({err_rate:.1f}%), "
        f"p95={interval_p95:>7.1f}ms, "
        f"qpm={interval_qpm:>6}"
    )


async def _wait_with_rollups(
    *,
    wait_seconds: int,
    rollup_sec: int,
    latencies: List[float],
    errors: List[str],
    elapsed_before: int,
) -> None:
    """Sleep for wait_seconds, printing rollup lines every rollup_sec seconds."""
    if rollup_sec <= 0 or wait_seconds <= 0:
        await asyncio.sleep(wait_seconds)
        return

    remaining = wait_seconds
    while remaining > 0:
        interval = min(rollup_sec, remaining)
        snapshot_lat_start = len(latencies)
        snapshot_err_start = len(errors)

        await asyncio.sleep(interval)
        remaining -= interval

        interval_lats = latencies[snapshot_lat_start:]
        interval_errs = errors[snapshot_err_start:]
        interval_p95 = percentile(interval_lats, 95) if interval_lats else 0.0

        _print_rollup(
            elapsed_sec=elapsed_before + (wait_seconds - remaining),
            interval_reqs=len(interval_lats),
            interval_errors=len(interval_errs),
            interval_p95=interval_p95,
            interval_sec=interval,
        )


async def run_load_test(
    base_url: str, vus: int, duration: int, target_qpm: int = 0, rollup_sec: int = 0,
):
    """Run the load test with given parameters."""
    url = f"{base_url}/ml/rerank"
    latencies: List[float] = []
    errors: List[str] = []
    stop_event = asyncio.Event()
    limiter = TokenBucketLimiter(target_qpm) if target_qpm > 0 else None

    print(f"\n[START] Load test: {vus} VUs, {duration}s, target: {url}")
    if target_qpm > 0:
        print(f"   Target QPM: {target_qpm} (≈{target_qpm / 60:.1f} req/s)")
    else:
        print(f"   Target QPM: unlimited (max throughput)")
    if rollup_sec > 0:
        print(f"   Rollup every {rollup_sec}s")
    print(f"   RERANK_MODE should be 'mock' for pure QPM measurement\n")

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(
                worker(client, url, duration, latencies, errors, stop_event, limiter)
            )
            for _ in range(vus)
        ]
        await _wait_with_rollups(
            wait_seconds=duration,
            rollup_sec=rollup_sec,
            latencies=latencies,
            errors=errors,
            elapsed_before=0,
        )
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    return _print_results(
        vus=vus,
        duration=duration,
        target_qpm=target_qpm,
        latencies=latencies,
        errors=errors,
    )


async def run_stepped_load_test(
    base_url: str,
    vus: int,
    steps: List[Tuple[int, int]],
    stop_error_rate: Optional[float] = None,
    stop_p95_ms: Optional[float] = None,
    rollup_sec: int = 0,
):
    """Run a stepped load test — each step changes the target QPM.

    Args:
        base_url: Server base URL.
        vus: Number of virtual users (concurrency).
        steps: List of (target_qpm, duration_sec) tuples.
        stop_error_rate: If set, stop when step error rate exceeds this (0.0–1.0).
        stop_p95_ms: If set, stop when step p95 latency exceeds this (ms).
        rollup_sec: If > 0, print periodic rollup every N seconds within each step.
    """
    url = f"{base_url}/ml/rerank"
    all_latencies: List[float] = []
    all_errors: List[str] = []
    stop_event = asyncio.Event()
    total_duration = sum(dur for _, dur in steps)
    actual_elapsed = 0

    # Start with the first step's QPM
    limiter = TokenBucketLimiter(steps[0][0])

    steps_desc = " → ".join(f"{qpm}QPM×{dur}s" for qpm, dur in steps)
    print(f"\n[START] Stepped load test: {vus} VUs, steps: {steps_desc}")
    if stop_error_rate is not None:
        print(f"   Stop on error rate > {stop_error_rate:.2%}")
    if stop_p95_ms is not None:
        print(f"   Stop on p95 > {stop_p95_ms:.0f}ms")
    if rollup_sec > 0:
        print(f"   Rollup every {rollup_sec}s")
    print(f"   Total duration: {total_duration}s, target: {url}")
    print(f"   RERANK_MODE should be 'mock' for pure QPM measurement\n")

    break_step_qpm: Optional[int] = None

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(
                worker(client, url, total_duration, all_latencies, all_errors, stop_event, limiter)
            )
            for _ in range(vus)
        ]

        # Run through each step
        for step_idx, (step_qpm, step_dur) in enumerate(steps):
            step_start_count = len(all_latencies)
            step_start_errors = len(all_errors)

            limiter.update_rate(step_qpm)
            qpm_label = str(step_qpm) if step_qpm > 0 else "unlimited"
            print(f"[STEP {step_idx + 1}/{len(steps)}] QPM={qpm_label}, duration={step_dur}s")

            await _wait_with_rollups(
                wait_seconds=step_dur,
                rollup_sec=rollup_sec,
                latencies=all_latencies,
                errors=all_errors,
                elapsed_before=actual_elapsed,
            )
            actual_elapsed += step_dur

            # Per-step summary line
            step_reqs = len(all_latencies) - step_start_count
            step_errs = len(all_errors) - step_start_errors
            step_lats = all_latencies[step_start_count:]
            step_p95 = percentile(step_lats, 95) if step_lats else 0.0
            step_actual_qpm = int(step_reqs / step_dur * 60) if step_dur > 0 else 0
            print(
                f"         → reqs={step_reqs}, errors={step_errs}, "
                f"p95={step_p95:.1f}ms, actual_qpm={step_actual_qpm}"
            )

            # Check stop conditions
            stop, reason = should_stop_step(
                step_errors=step_errs,
                step_total=step_reqs,
                step_p95_ms=step_p95,
                max_error_rate=stop_error_rate,
                max_p95_ms=stop_p95_ms,
            )
            if stop:
                break_step_qpm = step_qpm
                print(
                    f"\n[STOP] Threshold exceeded at step {step_idx + 1}: {reason}"
                )
                print(f"       break_step={step_qpm}qpm")
                break

        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    result = _print_results(
        vus=vus,
        duration=actual_elapsed,
        target_qpm=0,  # stepped mode — no single target
        latencies=all_latencies,
        errors=all_errors,
        label="Stepped Load Test Results",
    )
    if break_step_qpm is not None:
        result["break_step_qpm"] = break_step_qpm
    return result


def main():
    parser = argparse.ArgumentParser(description="ML Rerank QPM Load Test")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="Target server URL"
    )
    parser.add_argument("--vus", type=int, default=5, help="Virtual users (concurrency)")
    parser.add_argument("--duration", type=int, default=10, help="Test duration in seconds")
    parser.add_argument(
        "--target-qpm",
        type=int,
        default=0,
        help="Target QPM rate limit (0=unlimited). E.g. --target-qpm 400",
    )
    parser.add_argument(
        "--steps",
        type=str,
        default="",
        help=(
            "Stepped QPM schedule: 'QPM:SEC,QPM:SEC,...'. "
            "E.g. --steps '400:30,1200:60'. Overrides --target-qpm and --duration."
        ),
    )
    parser.add_argument(
        "--stop-on-error-rate",
        type=float,
        default=None,
        help="Stop stepped test if step error rate exceeds this (0.0–1.0). E.g. 0.05",
    )
    parser.add_argument(
        "--stop-on-p95-ms",
        type=float,
        default=None,
        help="Stop stepped test if step p95 latency exceeds this (ms). E.g. 1500",
    )
    parser.add_argument(
        "--rollup-sec",
        type=int,
        default=0,
        help="Print periodic rollup every N seconds (0=disabled). E.g. --rollup-sec 60",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="mock",
        choices=["simulated", "mock", "local"],
        help="Rerank mode: simulated|mock|local (default: mock)",
    )
    parser.add_argument(
        "--sim-timeout-rate",
        type=float,
        default=None,
        help="Simulated timeout rate (0.0–1.0). E.g. 0.01",
    )
    parser.add_argument(
        "--sim-rate-limit-rate",
        type=float,
        default=None,
        help="Simulated rate-limit error rate (0.0–1.0). E.g. 0.02",
    )
    parser.add_argument(
        "--sim-latency-ms",
        type=int,
        default=None,
        help="Simulated base latency in ms. E.g. 300",
    )
    parser.add_argument(
        "--sim-jitter-ms",
        type=int,
        default=None,
        help="Simulated latency jitter in ms. E.g. 150",
    )
    args = parser.parse_args()

    # Force vendor OFF before test, then set mode/sim env, restore all after
    _force_vendor_off()
    _force_mode_env(
        mode=args.mode,
        sim_timeout_rate=args.sim_timeout_rate,
        sim_rate_limit_rate=args.sim_rate_limit_rate,
        sim_latency_ms=args.sim_latency_ms,
        sim_jitter_ms=args.sim_jitter_ms,
    )
    try:
        if args.steps:
            steps = parse_steps(args.steps)
            asyncio.run(
                run_stepped_load_test(
                    args.base_url,
                    args.vus,
                    steps,
                    stop_error_rate=args.stop_on_error_rate,
                    stop_p95_ms=args.stop_on_p95_ms,
                    rollup_sec=args.rollup_sec,
                )
            )
        else:
            asyncio.run(
                run_load_test(
                    args.base_url,
                    args.vus,
                    args.duration,
                    args.target_qpm,
                    rollup_sec=args.rollup_sec,
                )
            )
    finally:
        _restore_env()


if __name__ == "__main__":
    main()
