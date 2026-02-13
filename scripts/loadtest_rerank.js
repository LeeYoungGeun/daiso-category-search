/**
 * k6 Load Test — /ml/rerank QPM Measurement
 *
 * Usage:
 *   k6 run scripts/loadtest_rerank.js
 *   k6 run --vus 10 --duration 30s scripts/loadtest_rerank.js
 *
 *   # Target QPM mode (400 QPM = ~6.67 req/s):
 *   k6 run -e TARGET_QPM=400 scripts/loadtest_rerank.js
 *
 *   # Stepped QPM spike (400→1200 QPM):
 *   k6 run -e STEPS="400:30,1200:60" scripts/loadtest_rerank.js
 *
 *   # Stepped with stop conditions:
 *   k6 run -e STEPS="400:60,800:60,1200:60" -e STOP_ERROR_RATE=0.05 -e STOP_P95_MS=1500 scripts/loadtest_rerank.js
 *
 *   # Simulated failure injection:
 *   k6 run -e MODE=simulated -e SIM_TIMEOUT_RATE=0.01 -e SIM_LATENCY_MS=300 scripts/loadtest_rerank.js
 *
 * Environment:
 *   BASE_URL            — target server (default: http://localhost:8000)
 *   TARGET_QPM          — target queries per minute (default: 0 = use default scenarios)
 *   STEPS               — stepped QPM schedule: "QPM:SEC,QPM:SEC,..." (overrides TARGET_QPM)
 *   STOP_ERROR_RATE     — abort if error rate exceeds this (0.0–1.0, default: disabled)
 *   STOP_P95_MS         — abort if p95 latency exceeds this (ms, default: disabled)
 *   ROLLUP_SEC          — k6 native: use `--out csv=results.csv` for periodic data.
 *   MODE                — rerank mode: simulated|mock|local (default: mock).
 *                          Server must be started with matching RERANK_MODE.
 *   SIM_TIMEOUT_RATE    — simulated timeout rate (0.0–1.0)
 *   SIM_RATE_LIMIT_RATE — simulated rate-limit error rate (0.0–1.0)
 *   SIM_LATENCY_MS      — simulated base latency in ms
 *   SIM_JITTER_MS       — simulated latency jitter in ms
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
const vendorCalledCount = new Counter("vendor_called_count");
const vendorSuspectCount = new Counter("vendor_suspect_count");

// ── Options ─────────────────────────────────────────────────────────────────
const TARGET_QPM = parseInt(__ENV.TARGET_QPM || "0", 10);
const STEPS_RAW = __ENV.STEPS || "";

/**
 * Parse a steps string like "400:30,1200:60" into [{qpm, duration}, ...].
 * Returns empty array if input is empty.
 */
function parseSteps(stepsStr) {
  if (!stepsStr || !stepsStr.trim()) return [];
  return stepsStr.split(",").map((seg) => {
    const parts = seg.trim().split(":");
    if (parts.length !== 2) throw new Error(`Invalid step format: ${seg}`);
    const qpm = parseInt(parts[0].trim(), 10);
    const dur = parseInt(parts[1].trim(), 10);
    if (isNaN(qpm) || isNaN(dur) || qpm < 0 || dur <= 0) {
      throw new Error(`Invalid step values: ${seg}`);
    }
    return { qpm, duration: dur };
  });
}

const PARSED_STEPS = parseSteps(STEPS_RAW);

function buildScenarios() {
  // When STEPS is set, use ramping-arrival-rate with stages
  if (PARSED_STEPS.length > 0) {
    const preAllocVUs = parseInt(__ENV.VUS || "10", 10);
    // Build stages: each step becomes a stage that ramps to the target rate
    const stages = [];
    for (const step of PARSED_STEPS) {
      const ratePerSec = Math.max(1, Math.round(step.qpm / 60));
      stages.push({ duration: `${step.duration}s`, target: ratePerSec });
    }
    const totalDuration = PARSED_STEPS.reduce((sum, s) => sum + s.duration, 0);
    return {
      stepped_qpm: {
        executor: "ramping-arrival-rate",
        startRate: stages[0].target,
        timeUnit: "1s",
        stages: stages,
        preAllocatedVUs: preAllocVUs,
        maxVUs: preAllocVUs * 3,
        tags: { scenario: "stepped_qpm" },
      },
    };
  }

  // When TARGET_QPM is set, use constant-arrival-rate to enforce exact request rate
  if (TARGET_QPM > 0) {
    const ratePerSec = Math.max(1, Math.round(TARGET_QPM / 60));
    const duration = __ENV.DURATION || "600s";
    const preAllocVUs = parseInt(__ENV.VUS || "10", 10);
    return {
      target_qpm: {
        executor: "constant-arrival-rate",
        rate: ratePerSec,
        timeUnit: "1s",
        duration: duration,
        preAllocatedVUs: preAllocVUs,
        maxVUs: preAllocVUs * 3,
        tags: { scenario: "target_qpm" },
      },
    };
  }

  // Default: multi-scenario (smoke → load → spike)
  return {
    smoke: {
      executor: "constant-vus",
      vus: 1,
      duration: "10s",
      tags: { scenario: "smoke" },
    },
    load: {
      executor: "constant-vus",
      vus: 5,
      duration: "30s",
      startTime: "12s",
      tags: { scenario: "load" },
    },
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "5s", target: 20 },
        { duration: "10s", target: 20 },
        { duration: "5s", target: 0 },
      ],
      startTime: "44s",
      tags: { scenario: "spike" },
    },
  };
}

// ── Stop condition env vars ─────────────────────────────────────────────────
const STOP_ERROR_RATE = __ENV.STOP_ERROR_RATE ? parseFloat(__ENV.STOP_ERROR_RATE) : 0;
const STOP_P95_MS = __ENV.STOP_P95_MS ? parseFloat(__ENV.STOP_P95_MS) : 0;

function buildThresholds() {
  const thresholds = {
    http_req_duration: ["p(95)<500", "p(99)<1000"],
    http_req_failed: ["rate<0.01"],
    rerank_latency_ms: ["p(95)<200"],
  };

  // When stop conditions are set, add abortOnFail thresholds
  if (STOP_ERROR_RATE > 0) {
    // k6 threshold: abort if error rate exceeds the limit
    thresholds.http_req_failed = [
      {
        threshold: `rate<${STOP_ERROR_RATE}`,
        abortOnFail: true,
        delayAbortEval: "10s", // evaluate after 10s to avoid false positives
      },
    ];
  }
  if (STOP_P95_MS > 0) {
    thresholds.http_req_duration = [
      {
        threshold: `p(95)<${STOP_P95_MS}`,
        abortOnFail: true,
        delayAbortEval: "10s",
      },
    ];
  }

  return thresholds;
}

export const options = {
  scenarios: buildScenarios(),
  thresholds: buildThresholds(),
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

  // ── Vendor trace detection ──────────────────────────────────────────
  // Header check: X-Vendor-Called == "1"
  const vendorHeader = res.headers["X-Vendor-Called"];
  if (vendorHeader === "1") {
    vendorCalledCount.add(1);
  }

  // Body check: vendor_model or vendor_called keys present
  let bodyObj = null;
  try {
    bodyObj = res.json();
  } catch {
    // ignore parse errors — handled by checks below
  }
  if (bodyObj && ("vendor_model" in bodyObj || "vendor_called" in bodyObj)) {
    vendorSuspectCount.add(1);
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
    "no vendor_called header": (r) => r.headers["X-Vendor-Called"] !== "1",
    "no vendor keys in body": (_r) => {
      return !(bodyObj && ("vendor_model" in bodyObj || "vendor_called" in bodyObj));
    },
  });

  if (!ok) {
    rerankErrors.add(1);
  }

  // Small sleep to avoid pure CPU spin
  sleep(0.05);
}

// ── Setup: warn about vendor env ────────────────────────────────────────────
export function setup() {
  // k6 cannot modify the server's env, but we log a reminder.
  // The Python loadtest script handles env forcing; for k6, the user must
  // ensure VENDOR_ENABLED=false, VENDOR_SAMPLE_RATE=0 on the server side.
  console.log("[INFO] k6 vendor guard active — checking X-Vendor-Called header & body keys.");
  console.log("[INFO] Ensure server runs with VENDOR_ENABLED=false VENDOR_SAMPLE_RATE=0");

  if (PARSED_STEPS.length > 0) {
    const stepsDesc = PARSED_STEPS.map((s) => `${s.qpm}QPM×${s.duration}s`).join(" → ");
    console.log(`[INFO] Stepped QPM mode: ${stepsDesc}`);
    if (STOP_ERROR_RATE > 0) {
      console.log(`[INFO] Stop on error rate > ${(STOP_ERROR_RATE * 100).toFixed(1)}%`);
    }
    if (STOP_P95_MS > 0) {
      console.log(`[INFO] Stop on p95 > ${STOP_P95_MS}ms`);
    }
  } else if (TARGET_QPM > 0) {
    console.log(`[INFO] Target QPM mode: ${TARGET_QPM} QPM (≈${Math.round(TARGET_QPM / 60)} req/s)`);
  }

  // k6 prints progress every ~1s natively. For soak tests, use:
  //   k6 run --out csv=results.csv scripts/loadtest_rerank.js
  // to get per-second data for trend analysis.
  console.log("[INFO] k6 prints live progress. Use --out csv=FILE for detailed rollup data.");

  // Mode / simulation info
  const mode = __ENV.MODE || "mock";
  console.log(`[INFO] Mode: ${mode}`);
  if (mode === "simulated") {
    const simVars = ["SIM_TIMEOUT_RATE", "SIM_RATE_LIMIT_RATE", "SIM_LATENCY_MS", "SIM_JITTER_MS"];
    for (const key of simVars) {
      if (__ENV[key]) {
        console.log(`[INFO]   ${key}=${__ENV[key]}`);
      }
    }
    console.log("[INFO] Ensure server runs with RERANK_MODE=simulated and matching SIM_* env vars.");
  }

  const rerank_mode = __ENV.RERANK_MODE || __ENV.MODE || "";
  if (rerank_mode && rerank_mode !== "mock" && rerank_mode !== "rule" && rerank_mode !== "simulated") {
    console.warn(
      `[WARN] RERANK_MODE=${rerank_mode} — vendor calls may occur server-side. ` +
      "Consider RERANK_MODE=mock for load tests."
    );
  }
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

  // Vendor counters
  const vendorCalled = data.metrics.vendor_called_count
    ? data.metrics.vendor_called_count.values.count
    : 0;
  const vendorSuspect = data.metrics.vendor_suspect_count
    ? data.metrics.vendor_suspect_count.values.count
    : 0;

  const summary = `
╔══════════════════════════════════════════════════════╗
║           ML Rerank QPM Load Test Results            ║
╠══════════════════════════════════════════════════════╣
║  Total Requests : ${String(totalReqs).padStart(8)}                         ║
║  Duration (sec) : ${String(Math.round(durationSec)).padStart(8)}                         ║
║  Mode           : ${String(PARSED_STEPS.length > 0 ? "stepped" : TARGET_QPM > 0 ? TARGET_QPM + " QPM" : "unlimited").padStart(8)}                         ║
║  QPM (actual)   : ${String(qpm).padStart(8)}                         ║
║  vendor_called  : ${String(vendorCalled).padStart(8)}   (should be 0)         ║
║  vendor_suspect : ${String(vendorSuspect).padStart(8)}   (should be 0)         ║
║  p50 latency    : ${String(typeof p50 === "number" ? p50.toFixed(1) + "ms" : p50).padStart(10)}                       ║
║  p95 latency    : ${String(typeof p95 === "number" ? p95.toFixed(1) + "ms" : p95).padStart(10)}                       ║
║  p99 latency    : ${String(typeof p99 === "number" ? p99.toFixed(1) + "ms" : p99).padStart(10)}                       ║
╚══════════════════════════════════════════════════════╝
`;

  if (vendorCalled > 0 || vendorSuspect > 0) {
    console.error("[FAIL] Vendor calls detected during load test!");
  }

  console.log(summary);

  return {
    stdout: summary,
  };
}
