"""
Tests for TokenBucketLimiter, parse_steps, should_stop_step, and _force_mode_env
used in scripts/loadtest_rerank.py.

Verifies that the rate limiter approximately constrains throughput
to the target QPM (±10% tolerance), the steps parser works correctly,
the stop condition checker returns correct True/False, and mode env forcing works.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

# Add project root so we can import from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the limiter class directly from the script module
from importlib import util as importlib_util

_spec = importlib_util.spec_from_file_location(
    "loadtest_rerank",
    str(Path(__file__).resolve().parent.parent / "scripts" / "loadtest_rerank.py"),
)
assert _spec is not None and _spec.loader is not None, "Failed to load loadtest_rerank.py"
_mod = importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
TokenBucketLimiter = _mod.TokenBucketLimiter
parse_steps = _mod.parse_steps
should_stop_step = _mod.should_stop_step
_force_mode_env = _mod._force_mode_env
_restore_env = _mod._restore_env
_saved_env = _mod._saved_env


@pytest.mark.asyncio
async def test_token_bucket_limits_rate():
    """TokenBucketLimiter should limit throughput to ~target QPM (±10%)."""
    target_qpm = 600  # 10 req/s — easy to measure in a short window
    test_duration = 2.0  # seconds
    expected_count = target_qpm / 60 * test_duration  # 20 requests

    limiter = TokenBucketLimiter(target_qpm)
    count = 0
    start = time.monotonic()

    while (time.monotonic() - start) < test_duration:
        await limiter.acquire()
        count += 1

    elapsed = time.monotonic() - start
    actual_qpm = count / elapsed * 60

    # Allow ±10% tolerance
    assert actual_qpm < target_qpm * 1.10, (
        f"Rate too high: {actual_qpm:.0f} QPM vs target {target_qpm}"
    )
    assert actual_qpm > target_qpm * 0.90, (
        f"Rate too low: {actual_qpm:.0f} QPM vs target {target_qpm}"
    )


@pytest.mark.asyncio
async def test_token_bucket_unlimited_when_zero():
    """TokenBucketLimiter with target_qpm=0 should not block."""
    limiter = TokenBucketLimiter(0)
    count = 0
    start = time.monotonic()

    # Should complete nearly instantly (no sleeping)
    for _ in range(100):
        await limiter.acquire()
        count += 1

    elapsed = time.monotonic() - start
    assert count == 100
    # 100 no-op acquires should take < 0.1s
    assert elapsed < 0.1, f"Unlimited limiter took too long: {elapsed:.3f}s"


def test_parse_steps_basic():
    """parse_steps should parse 'QPM:SEC,QPM:SEC' into list of tuples."""
    result = parse_steps("400:30,1200:60")
    assert result == [(400, 30), (1200, 60)]


def test_parse_steps_single():
    """parse_steps should handle a single step."""
    result = parse_steps("600:120")
    assert result == [(600, 120)]


def test_parse_steps_whitespace():
    """parse_steps should tolerate whitespace."""
    result = parse_steps(" 400 : 30 , 1200 : 60 ")
    assert result == [(400, 30), (1200, 60)]


def test_parse_steps_three_steps():
    """parse_steps should handle three or more steps."""
    result = parse_steps("200:10,400:20,1200:60")
    assert result == [(200, 10), (400, 20), (1200, 60)]


def test_parse_steps_zero_qpm():
    """parse_steps should allow QPM=0 (unlimited)."""
    result = parse_steps("0:30,400:60")
    assert result == [(0, 30), (400, 60)]


def test_parse_steps_invalid_format():
    """parse_steps should raise ValueError on bad format."""
    with pytest.raises(ValueError):
        parse_steps("400-30,1200:60")


def test_parse_steps_empty():
    """parse_steps should raise ValueError on empty string."""
    with pytest.raises(ValueError):
        parse_steps("")


def test_parse_steps_negative_duration():
    """parse_steps should raise ValueError on negative duration."""
    with pytest.raises(ValueError):
        parse_steps("400:-10")


# ── should_stop_step tests ───────────────────────────────────────────────────

def test_should_stop_step_no_thresholds():
    """No thresholds set → never stop."""
    stop, reason = should_stop_step(
        step_errors=50, step_total=100, step_p95_ms=2000.0,
    )
    assert stop is False
    assert reason == ""


def test_should_stop_step_error_rate_exceeded():
    """Error rate exceeds threshold → stop."""
    stop, reason = should_stop_step(
        step_errors=10, step_total=100, step_p95_ms=100.0,
        max_error_rate=0.05,
    )
    assert stop is True
    assert "error_rate" in reason


def test_should_stop_step_error_rate_ok():
    """Error rate within threshold → don't stop."""
    stop, reason = should_stop_step(
        step_errors=3, step_total=100, step_p95_ms=100.0,
        max_error_rate=0.05,
    )
    assert stop is False
    assert reason == ""


def test_should_stop_step_p95_exceeded():
    """p95 exceeds threshold → stop."""
    stop, reason = should_stop_step(
        step_errors=0, step_total=100, step_p95_ms=2000.0,
        max_p95_ms=1500.0,
    )
    assert stop is True
    assert "p95" in reason


def test_should_stop_step_p95_ok():
    """p95 within threshold → don't stop."""
    stop, reason = should_stop_step(
        step_errors=0, step_total=100, step_p95_ms=1000.0,
        max_p95_ms=1500.0,
    )
    assert stop is False
    assert reason == ""


def test_should_stop_step_both_thresholds_error_first():
    """Both thresholds set, error rate triggers first."""
    stop, reason = should_stop_step(
        step_errors=20, step_total=100, step_p95_ms=2000.0,
        max_error_rate=0.05, max_p95_ms=1500.0,
    )
    assert stop is True
    assert "error_rate" in reason  # error_rate checked first


def test_should_stop_step_zero_requests():
    """Zero requests → never stop (avoid division by zero)."""
    stop, reason = should_stop_step(
        step_errors=0, step_total=0, step_p95_ms=0.0,
        max_error_rate=0.05, max_p95_ms=1500.0,
    )
    assert stop is False


# ── _force_mode_env tests ────────────────────────────────────────────────────

def test_force_mode_env_simulated():
    """mode=simulated should set RERANK_MODE=simulated and SIM_* env vars."""
    # Save current state
    orig_rerank = os.environ.get("RERANK_MODE")
    orig_sim_timeout = os.environ.get("SIM_TIMEOUT_RATE")
    orig_sim_latency = os.environ.get("SIM_LATENCY_MS")
    orig_saved = dict(_saved_env)

    try:
        _force_mode_env(
            mode="simulated",
            sim_timeout_rate=0.01,
            sim_latency_ms=300,
        )
        assert os.environ.get("RERANK_MODE") == "simulated"
        assert os.environ.get("SIM_TIMEOUT_RATE") == "0.01"
        assert os.environ.get("SIM_LATENCY_MS") == "300"
        # SIM_RATE_LIMIT_RATE and SIM_JITTER_MS should NOT be set (not provided)
        # (they may or may not exist from prior state, so we just check the ones we set)
    finally:
        # Restore original env
        _restore_env()
        # Double-check restore worked for RERANK_MODE
        if orig_rerank is None:
            assert "RERANK_MODE" not in os.environ or os.environ.get("RERANK_MODE") == orig_rerank
        else:
            os.environ["RERANK_MODE"] = orig_rerank
        if orig_sim_timeout is not None:
            os.environ["SIM_TIMEOUT_RATE"] = orig_sim_timeout
        if orig_sim_latency is not None:
            os.environ["SIM_LATENCY_MS"] = orig_sim_latency
        # Restore _saved_env to original
        _saved_env.clear()
        _saved_env.update(orig_saved)
