"""
M1 Hybrid Search Benchmark
Evaluates search quality using hit@k, MRR, NDCG metrics.

Usage:
    # From project root:
    python -m backend.search.benchmark

    # With specific testcases:
    python -m backend.search.benchmark --testcases poc/lyg/templates/testcases.v7.clean.tsv

    # Compare all modes:
    python -m backend.search.benchmark --modes hybrid,bm25_only,dense_only

    # Output JSON report:
    python -m backend.search.benchmark --output reports/benchmark.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Ensure project root is in path
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.search.config import HybridSearchConfig
from backend.search.hybrid import HybridSearchService, SearchResult


# ─── Test Case Types ──────────────────────────────────────────────────────────

DEFAULT_TESTCASES = "poc/lyg/templates/testcases.v7.clean.tsv"


@dataclass
class TestCase:
    case_id: str
    raw_text: str
    intent_text: str
    bm25_query_text: str
    expected_doc_ids: List[str]
    expected_category: str = ""
    needs_clarification: bool = False
    notes: str = ""


def parse_expected_doc_ids(s: str) -> List[str]:
    """Parse comma-separated or JSON-array doc IDs."""
    if not s:
        return []
    raw = s.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            arr = json.loads(raw.replace("'", '"'))
            return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [p.strip() for p in re.split(r"[,|]", raw) if p.strip()]


def read_testcases(path: str) -> List[TestCase]:
    """Read testcases TSV file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Testcases not found: {path}")

    cases: List[TestCase] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            expected = parse_expected_doc_ids(row.get("expected_doc_ids", ""))
            if not expected:
                continue  # skip cases without gold labels

            nc = (row.get("needs_clarification") or "").strip().lower()
            cases.append(TestCase(
                case_id=row.get("id", ""),
                raw_text=row.get("raw_text", ""),
                intent_text=row.get("intent_text", ""),
                bm25_query_text=row.get("bm25_query_text", ""),
                expected_doc_ids=expected,
                expected_category=row.get("expected_category", ""),
                needs_clarification=nc in ("true", "1", "yes"),
                notes=row.get("notes", ""),
            ))
    return cases


# ─── Metrics ──────────────────────────────────────────────────────────────────

def hit_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    """1.0 if any gold doc appears in top-k predictions, else 0.0."""
    gold = set(gold_ids or [])
    topk = list(pred_ids)[:k]
    return 1.0 if any(x in gold for x in topk) else 0.0


def precision_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    if k <= 0:
        return 0.0
    gold = set(gold_ids or [])
    topk = list(pred_ids)[:k]
    hit = sum(1 for x in topk if x in gold)
    return hit / float(k)


def recall_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    gold = set(gold_ids or [])
    if not gold:
        return 0.0
    topk = list(pred_ids)[:k]
    hit = sum(1 for x in topk if x in gold)
    return hit / float(len(gold))


def mrr(pred_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
    """Mean Reciprocal Rank."""
    gold = set(gold_ids or [])
    if not gold:
        return 0.0
    for i, x in enumerate(pred_ids):
        if x in gold:
            return 1.0 / float(i + 1)
    return 0.0


def ndcg_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain (binary relevance)."""
    gold = set(gold_ids or [])
    if not gold or k <= 0:
        return 0.0
    topk = list(pred_ids)[:k]
    import math
    dcg = 0.0
    for i, x in enumerate(topk):
        if x in gold:
            dcg += 1.0 / math.log2(i + 2)  # log2(rank+1), rank is 1-based
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


# ─── Benchmark Runner ─────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    case_id: str
    query: str
    expected: List[str]
    predicted: List[str]
    hit_1: float = 0.0
    hit_3: float = 0.0
    hit_5: float = 0.0
    hit_10: float = 0.0
    mrr_val: float = 0.0
    ndcg_5: float = 0.0
    ndcg_10: float = 0.0
    latency_ms: int = 0
    notes: str = ""


@dataclass
class BenchmarkReport:
    mode: str
    n_cases: int
    metrics: Dict[str, float]
    per_case: List[CaseResult]
    failures: List[CaseResult]  # cases where hit@5 == 0
    total_time_s: float = 0.0
    timestamp: str = ""


def run_benchmark(
    service: HybridSearchService,
    cases: List[TestCase],
    *,
    mode: str = "hybrid",
    query_field: str = "bm25_query_text",
    top_k: int = 30,
) -> BenchmarkReport:
    """Run benchmark on test cases.

    Args:
        service: HybridSearchService instance
        cases: List of test cases
        mode: Search mode ("hybrid", "bm25_only", "dense_only")
        query_field: Which field to use as query ("bm25_query_text", "raw_text", "intent_text")
        top_k: Number of results to retrieve

    Returns:
        BenchmarkReport with aggregated metrics
    """
    print(f"\n{'='*60}")
    print(f"  Benchmark: mode={mode}, query_field={query_field}, cases={len(cases)}")
    print(f"{'='*60}")

    results: List[CaseResult] = []
    start_time = time.time()

    for idx, tc in enumerate(cases):
        # Select query text
        if query_field == "raw_text":
            query = tc.raw_text
        elif query_field == "intent_text":
            query = tc.intent_text
        else:
            query = tc.bm25_query_text

        if not query.strip():
            query = tc.raw_text  # fallback

        # Execute search
        t0 = time.time()
        sr = service.search(query, top_k=top_k, mode=mode)
        latency = int((time.time() - t0) * 1000)

        pred_ids = [d.doc_id for d in sr.docs]

        cr = CaseResult(
            case_id=tc.case_id,
            query=query,
            expected=tc.expected_doc_ids,
            predicted=pred_ids[:10],
            hit_1=hit_at_k(pred_ids, tc.expected_doc_ids, 1),
            hit_3=hit_at_k(pred_ids, tc.expected_doc_ids, 3),
            hit_5=hit_at_k(pred_ids, tc.expected_doc_ids, 5),
            hit_10=hit_at_k(pred_ids, tc.expected_doc_ids, 10),
            mrr_val=mrr(pred_ids, tc.expected_doc_ids),
            ndcg_5=ndcg_at_k(pred_ids, tc.expected_doc_ids, 5),
            ndcg_10=ndcg_at_k(pred_ids, tc.expected_doc_ids, 10),
            latency_ms=latency,
            notes=tc.notes,
        )
        results.append(cr)

        # Progress
        status = "✅" if cr.hit_5 > 0 else "❌"
        if (idx + 1) % 10 == 0 or idx == len(cases) - 1:
            print(f"  [{idx+1}/{len(cases)}] {status} {tc.case_id}: hit@5={cr.hit_5:.0f} mrr={cr.mrr_val:.3f} ({latency}ms)")

    total_time = time.time() - start_time

    # Aggregate metrics
    n = len(results)
    metrics = {
        "hit@1": sum(r.hit_1 for r in results) / n if n else 0,
        "hit@3": sum(r.hit_3 for r in results) / n if n else 0,
        "hit@5": sum(r.hit_5 for r in results) / n if n else 0,
        "hit@10": sum(r.hit_10 for r in results) / n if n else 0,
        "mrr": sum(r.mrr_val for r in results) / n if n else 0,
        "ndcg@5": sum(r.ndcg_5 for r in results) / n if n else 0,
        "ndcg@10": sum(r.ndcg_10 for r in results) / n if n else 0,
        "avg_latency_ms": sum(r.latency_ms for r in results) / n if n else 0,
        "p95_latency_ms": sorted([r.latency_ms for r in results])[int(n * 0.95)] if n else 0,
    }

    failures = [r for r in results if r.hit_5 == 0]

    report = BenchmarkReport(
        mode=mode,
        n_cases=n,
        metrics=metrics,
        per_case=results,
        failures=failures,
        total_time_s=round(total_time, 1),
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Print summary
    print(f"\n{'─'*60}")
    print(f"  📊 Results: {mode}")
    print(f"{'─'*60}")
    for k, v in metrics.items():
        if "latency" in k:
            print(f"  {k:>20s}: {v:.0f} ms")
        else:
            print(f"  {k:>20s}: {v:.4f} ({v*100:.1f}%)")
    print(f"  {'failures':>20s}: {len(failures)}/{n}")
    print(f"  {'total_time':>20s}: {total_time:.1f}s")

    if failures:
        print(f"\n  ❌ Failed cases (hit@5=0):")
        for f in failures[:10]:
            print(f"    - {f.case_id}: query='{f.query[:50]}' expected={f.expected}")

    return report


def report_to_dict(report: BenchmarkReport) -> Dict[str, Any]:
    """Convert report to serializable dict."""
    return {
        "mode": report.mode,
        "n_cases": report.n_cases,
        "metrics": {k: round(v, 4) for k, v in report.metrics.items()},
        "failures": [
            {"case_id": f.case_id, "query": f.query[:80], "expected": f.expected}
            for f in report.failures
        ],
        "total_time_s": report.total_time_s,
        "timestamp": report.timestamp,
    }


def report_to_markdown(reports: List[BenchmarkReport]) -> str:
    """Generate markdown comparison table."""
    lines = [
        "# M1 Hybrid Search Benchmark Report",
        "",
        f"**Date**: {reports[0].timestamp if reports else 'N/A'}",
        f"**Test Cases**: {reports[0].n_cases if reports else 0}",
        "",
        "## Results Comparison",
        "",
        "| Metric | " + " | ".join(r.mode for r in reports) + " |",
        "|--------|" + "|".join("--------" for _ in reports) + "|",
    ]

    metric_keys = ["hit@1", "hit@3", "hit@5", "hit@10", "mrr", "ndcg@5", "ndcg@10", "avg_latency_ms"]
    for mk in metric_keys:
        vals = []
        for r in reports:
            v = r.metrics.get(mk, 0)
            if "latency" in mk:
                vals.append(f"{v:.0f}ms")
            else:
                vals.append(f"{v*100:.1f}%")
        lines.append(f"| {mk} | " + " | ".join(vals) + " |")

    lines.append("")
    lines.append("## Failures")
    for r in reports:
        if r.failures:
            lines.append(f"\n### {r.mode} ({len(r.failures)} failures)")
            for f in r.failures[:20]:
                lines.append(f"- **{f.case_id}**: `{f.query[:60]}` → expected: {f.expected}")

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="M1 Hybrid Search Benchmark")
    parser.add_argument("--testcases", default=DEFAULT_TESTCASES, help="Path to testcases TSV")
    parser.add_argument("--modes", default="hybrid,bm25_only,dense_only", help="Comma-separated search modes")
    parser.add_argument("--query-field", default="bm25_query_text", help="Query field: bm25_query_text, raw_text, intent_text")
    parser.add_argument("--top-k", type=int, default=30, help="Top-K retrieval")
    parser.add_argument("--output", default=None, help="Output JSON report path")
    parser.add_argument("--markdown", default=None, help="Output markdown report path")
    args = parser.parse_args()

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Read test cases
    print(f"📂 Reading testcases: {args.testcases}")
    cases = read_testcases(args.testcases)
    print(f"  📊 {len(cases)} test cases loaded")

    # Initialize service
    config = HybridSearchConfig.from_env()
    service = HybridSearchService(config)

    # Health check
    health = service.health_check()
    print(f"\n🏥 Health check: {health}")
    if not all(health.values()):
        print("⚠️  Some services are not healthy. Results may be incomplete.")

    # Run benchmarks
    modes = [m.strip() for m in args.modes.split(",")]
    reports: List[BenchmarkReport] = []

    for mode in modes:
        report = run_benchmark(
            service,
            cases,
            mode=mode,
            query_field=args.query_field,
            top_k=args.top_k,
        )
        reports.append(report)

    # Output
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([report_to_dict(r) for r in reports], f, indent=2, ensure_ascii=False)
        print(f"\n📄 JSON report saved: {args.output}")

    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        md = report_to_markdown(reports)
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\n📄 Markdown report saved: {args.markdown}")

    # Print final comparison
    if len(reports) > 1:
        print(f"\n{'='*60}")
        print("  📊 Final Comparison")
        print(f"{'='*60}")
        header = f"{'Metric':>20s}"
        for r in reports:
            header += f" | {r.mode:>12s}"
        print(header)
        print("-" * len(header))
        for mk in ["hit@1", "hit@3", "hit@5", "hit@10", "mrr", "ndcg@5", "ndcg@10"]:
            row = f"{mk:>20s}"
            for r in reports:
                v = r.metrics.get(mk, 0)
                row += f" | {v*100:>10.1f}%"
            print(row)


if __name__ == "__main__":
    main()
