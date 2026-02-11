/**
 * k6 Load Test — /ml/rerank QPM Measurement
 *
 * Usage:
 *   k6 run scripts/loadtest_rerank.js
 *   k6 run --vus 10 --duration 30s scripts/loadtest_rerank.js
 *
 * Environment:
 *   BASE_URL  — target server (default: http://localhost:8000)
 *
 * Prerequisites:
 *   1. Install k6: https://k6.io/docs/get-started/installation/
 *      - Windows: choco install k6  OR  winget install k6
 *      - macOS:   brew install k6
 *   2. Start the dev server:
 *      set RERANK_MODE=mock && python -m uvicorn backend.dev_server:app --port 8000
 *   3. Run this script:
 *      k6 run scripts/loadtest_rerank.js
 *
 * Output metrics:
 *   - http_req_duration: p50, p95, p99 latency
 *   - http_reqs:         total requests → QPM = http_reqs * (60 / duration_sec)
 *   - rerank_latency_ms: custom metric from X-Rerank-Latency-Ms header
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";

// ── Custom metrics ──────────────────────────────────────────────────────────
const rerankLatency = new Trend("rerank_latency_ms", true);
const rerankErrors = new Counter("rerank_errors");

// ── Options ─────────────────────────────────────────────────────────────────
export const options = {
  scenarios: {
    // Scenario 1: Smoke test (baseline)
    smoke: {
      executor: "constant-vus",
      vus: 1,
      duration: "10s",
      tags: { scenario: "smoke" },
    },
    // Scenario 2: Load test (QPM measurement)
    load: {
      executor: "constant-vus",
      vus: 5,
      duration: "30s",
      startTime: "12s", // start after smoke
      tags: { scenario: "load" },
    },
    // Scenario 3: Spike test
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "5s", target: 20 },
        { duration: "10s", target: 20 },
        { duration: "5s", target: 0 },
      ],
      startTime: "44s", // start after load
      tags: { scenario: "spike" },
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<500", "p(99)<1000"], // 95th < 500ms
    http_req_failed: ["rate<0.01"],                  // <1% errors
    rerank_latency_ms: ["p(95)<200"],                // rerank p95 < 200ms
  },
};

// ── Test data ───────────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

const PAYLOADS = [
  {
    query: "튀김 건질 때 쓰는 거",
    candidates: [
      { id: "1", name: "스텐 채반", desc: "튀김/면 요리용 채반" },
      { id: "2", name: "세탁망 원형", desc: "세탁기용 망" },
      { id: "3", name: "튀김가루 1kg", desc: "식재료" },
    ],
  },
  {
    query: "파란색 볼펜",
    candidates: [
      { id: "10", name: "모나미 볼펜 파랑", desc: "필기구" },
      { id: "11", name: "빨간 볼펜", desc: "필기구" },
    ],
  },
  {
    query: "겨울에 창문에 붙이는 뽁뽁이",
    candidates: [
      { id: "20", name: "단열 시트 에어캡", desc: "창문 단열용" },
      { id: "21", name: "장난감 뽁뽁이", desc: "스트레스 해소" },
    ],
  },
  {
    query: "주방 세제",
    candidates: [
      { id: "30", name: "퐁퐁 주방세제", desc: "설거지용" },
      { id: "31", name: "세탁 세제", desc: "세탁기용" },
      { id: "32", name: "욕실 세정제", desc: "욕실 청소용" },
    ],
  },
  {
    query: "아이폰 충전기",
    candidates: [
      { id: "40", name: "건전지 AA 2개입", desc: "배터리" },
      { id: "41", name: "갤럭시 C타입 케이블", desc: "삼성 호환" },
    ],
  },
];

// ── Main test function ──────────────────────────────────────────────────────
export default function () {
  const payload = PAYLOADS[Math.floor(Math.random() * PAYLOADS.length)];

  const res = http.post(`${BASE_URL}/ml/rerank`, JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    tags: { endpoint: "ml_rerank" },
  });

  // Record custom latency from response header
  const latencyHeader = res.headers["X-Rerank-Latency-Ms"];
  if (latencyHeader) {
    rerankLatency.add(parseInt(latencyHeader, 10));
  }

  // Checks
  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
    "has selected_id": (r) => {
      try {
        const body = r.json();
        return "selected_id" in body;
      } catch {
        return false;
      }
    },
    "has latency_ms": (r) => {
      try {
        const body = r.json();
        return typeof body.latency_ms === "number";
      } catch {
        return false;
      }
    },
    "has is_fallback": (r) => {
      try {
        const body = r.json();
        return typeof body.is_fallback === "boolean";
      } catch {
        return false;
      }
    },
    "has error_type": (r) => {
      try {
        const body = r.json();
        return "error_type" in body;
      } catch {
        return false;
      }
    },
  });

  if (!ok) {
    rerankErrors.add(1);
  }

  // Small sleep to avoid pure CPU spin
  sleep(0.05);
}

// ── Summary ─────────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const totalReqs = data.metrics.http_reqs ? data.metrics.http_reqs.values.count : 0;
  const durationSec =
    data.state && data.state.testRunDurationMs
      ? data.state.testRunDurationMs / 1000
      : 64; // approximate total scenario time

  const qpm = durationSec > 0 ? Math.round((totalReqs / durationSec) * 60) : 0;

  const p50 = data.metrics.http_req_duration
    ? data.metrics.http_req_duration.values["p(50)"]
    : "N/A";
  const p95 = data.metrics.http_req_duration
    ? data.metrics.http_req_duration.values["p(95)"]
    : "N/A";
  const p99 = data.metrics.http_req_duration
    ? data.metrics.http_req_duration.values["p(99)"]
    : "N/A";

  const summary = `
╔══════════════════════════════════════════════════════╗
║           ML Rerank QPM Load Test Results            ║
╠══════════════════════════════════════════════════════╣
║  Total Requests : ${String(totalReqs).padStart(8)}                         ║
║  Duration (sec) : ${String(Math.round(durationSec)).padStart(8)}                         ║
║  QPM (est.)     : ${String(qpm).padStart(8)}                         ║
║  p50 latency    : ${String(typeof p50 === "number" ? p50.toFixed(1) + "ms" : p50).padStart(10)}                       ║
║  p95 latency    : ${String(typeof p95 === "number" ? p95.toFixed(1) + "ms" : p95).padStart(10)}                       ║
║  p99 latency    : ${String(typeof p99 === "number" ? p99.toFixed(1) + "ms" : p99).padStart(10)}                       ║
╚══════════════════════════════════════════════════════╝
`;

  console.log(summary);

  return {
    stdout: summary,
  };
}
