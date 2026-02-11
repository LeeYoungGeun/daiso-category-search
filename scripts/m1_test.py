"""
M1 End-to-End Test Script
Tests the full pipeline: Docker services → Index → Search → Benchmark

Usage:
    python scripts/m1_test.py                    # Full test
    python scripts/m1_test.py --step health      # Health check only
    python scripts/m1_test.py --step index       # Index only
    python scripts/m1_test.py --step search      # Search test only
    python scripts/m1_test.py --step benchmark   # Benchmark only
    python scripts/m1_test.py --step all         # All steps (default)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is in path
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def step_health():
    """Step 1: Health check for all Docker services."""
    print("\n" + "=" * 60)
    print("  Step 1: Health Check")
    print("=" * 60)

    import requests

    services = {
        "Elasticsearch": os.getenv("ELASTIC_URL", "http://localhost:9200"),
        "Qdrant": os.getenv("QDRANT_URL", "http://localhost:6333"),
        "Redis": None,  # checked separately
    }

    all_ok = True

    # Check Elasticsearch
    try:
        r = requests.get(f"{services['Elasticsearch']}/_cluster/health", timeout=5)
        if r.status_code == 200:
            data = r.json()
            print(f"  ✅ Elasticsearch: {data.get('status', 'unknown')} ({services['Elasticsearch']})")
        else:
            print(f"  ❌ Elasticsearch: HTTP {r.status_code}")
            all_ok = False
    except Exception as e:
        print(f"  ❌ Elasticsearch: {e}")
        all_ok = False

    # Check Qdrant
    try:
        r = requests.get(f"{services['Qdrant']}/healthz", timeout=5)
        if r.status_code == 200:
            print(f"  ✅ Qdrant: healthy ({services['Qdrant']})")
        else:
            print(f"  ❌ Qdrant: HTTP {r.status_code}")
            all_ok = False
    except Exception as e:
        print(f"  ❌ Qdrant: {e}")
        all_ok = False

    # Check Redis
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()
        print(f"  ✅ Redis: healthy ({redis_url})")
    except ImportError:
        print(f"  ⚠️  Redis: redis-py not installed (optional)")
    except Exception as e:
        print(f"  ❌ Redis: {e}")
        all_ok = False

    if all_ok:
        print("\n  🎉 All services healthy!")
    else:
        print("\n  ⚠️  Some services are not available.")
        print("  💡 Run: docker compose up -d")

    return all_ok


def step_index(clean: bool = True):
    """Step 2: Index catalog data."""
    print("\n" + "=" * 60)
    print("  Step 2: Index Catalog")
    print("=" * 60)

    from backend.search.indexer import index_catalog

    catalog_path = "poc/lyg/data/catalog.30cat.v3.tsv"
    if not os.path.exists(catalog_path):
        print(f"  ❌ Catalog not found: {catalog_path}")
        return False

    try:
        summary = index_catalog(catalog_path=catalog_path, clean=clean)
        return summary.get("status") == "ok"
    except Exception as e:
        print(f"  ❌ Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def step_search():
    """Step 3: Quick search test with sample queries."""
    print("\n" + "=" * 60)
    print("  Step 3: Search Test")
    print("=" * 60)

    from backend.search.config import HybridSearchConfig
    from backend.search.hybrid import HybridSearchService

    config = HybridSearchConfig.from_env()
    service = HybridSearchService(config)

    test_queries = [
        ("욕실 매트", ["bath_mat"]),
        ("건전지", ["battery_aa", "battery_aaa"]),
        ("충전 케이블", ["usb_cable", "charger"]),
        ("가위", ["scissors"]),
        ("샴푸", ["shampoo"]),
    ]

    modes = ["hybrid", "bm25_only", "dense_only"]
    all_ok = True

    for mode in modes:
        print(f"\n  ── Mode: {mode} ──")
        for query, expected in test_queries:
            result = service.search(query, top_k=5, mode=mode)
            pred_ids = [d.doc_id for d in result.docs]
            hit = any(e in pred_ids for e in expected)
            status = "✅" if hit else "❌"
            timing = result.timing_ms.get("total_ms", 0)
            print(f"    {status} '{query}' → {pred_ids[:3]} ({timing}ms)")
            if not hit:
                all_ok = False

    if all_ok:
        print("\n  🎉 All search tests passed!")
    else:
        print("\n  ⚠️  Some search tests failed.")

    return all_ok


def step_benchmark():
    """Step 4: Run full benchmark."""
    print("\n" + "=" * 60)
    print("  Step 4: Benchmark")
    print("=" * 60)

    from backend.search.config import HybridSearchConfig
    from backend.search.hybrid import HybridSearchService
    from backend.search.benchmark import (
        read_testcases,
        run_benchmark,
        report_to_dict,
        report_to_markdown,
    )

    testcases_path = "poc/lyg/templates/testcases.v7.clean.tsv"
    if not os.path.exists(testcases_path):
        print(f"  ❌ Testcases not found: {testcases_path}")
        return False

    cases = read_testcases(testcases_path)
    print(f"  📊 {len(cases)} test cases loaded")

    config = HybridSearchConfig.from_env()
    service = HybridSearchService(config)

    reports = []
    for mode in ["hybrid", "bm25_only", "dense_only"]:
        report = run_benchmark(service, cases, mode=mode)
        reports.append(report)

    # Save reports
    Path("reports").mkdir(exist_ok=True)

    json_path = "reports/m1_benchmark.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([report_to_dict(r) for r in reports], f, indent=2, ensure_ascii=False)
    print(f"\n  📄 JSON report: {json_path}")

    md_path = "reports/m1_benchmark.md"
    md = report_to_markdown(reports)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"  📄 Markdown report: {md_path}")

    # Check if hybrid hit@5 >= 95%
    hybrid_report = reports[0]
    hit5 = hybrid_report.metrics.get("hit@5", 0)
    if hit5 >= 0.95:
        print(f"\n  🎉 Hybrid hit@5 = {hit5*100:.1f}% ≥ 95% target!")
    else:
        print(f"\n  ⚠️  Hybrid hit@5 = {hit5*100:.1f}% < 95% target")

    return True


def main():
    parser = argparse.ArgumentParser(description="M1 End-to-End Test")
    parser.add_argument("--step", default="all", choices=["health", "index", "search", "benchmark", "all"])
    parser.add_argument("--no-clean", action="store_true", help="Don't clean before indexing")
    args = parser.parse_args()

    print("🚀 M1 Hybrid Search — End-to-End Test")
    print(f"   Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    if args.step in ("all", "health"):
        ok = step_health()
        if args.step == "health":
            sys.exit(0 if ok else 1)
        if not ok and args.step == "all":
            print("\n⚠️  Services not ready. Run: docker compose up -d")
            print("   Then retry: python scripts/m1_test.py")
            sys.exit(1)

    if args.step in ("all", "index"):
        ok = step_index(clean=not args.no_clean)
        if not ok:
            print("\n❌ Indexing failed. Aborting.")
            sys.exit(1)

    if args.step in ("all", "search"):
        step_search()

    if args.step in ("all", "benchmark"):
        step_benchmark()

    print("\n" + "=" * 60)
    print("  ✅ M1 Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
