from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ivhl.core.config import load_pipelines, load_vendor_sets
from ivhl.core.pipeline import run_benchmark


def _default_path(p: str) -> str:
    # Prefer repo-relative paths when run from project root
    cand = Path(p)
    if cand.exists():
        return str(cand)
    cand = Path.cwd() / p
    if cand.exists():
        return str(cand)
    return str(Path.cwd() / p)


def cmd_list(args: argparse.Namespace) -> int:
    vendors_yaml = args.vendors or _default_path("templates/vendors.example.yaml")
    pipelines_yaml = args.pipelines or _default_path("templates/pipeline.example.yaml")

    vendor_sets = load_vendor_sets(vendors_yaml)
    pipelines = load_pipelines(pipelines_yaml)

    print("Vendor Sets:")
    for k in sorted(vendor_sets.keys()):
        print(f"  - {k}")

    print("\nPipelines:")
    for k in sorted(pipelines.keys()):
        steps = ", ".join(pipelines[k].steps)
        print(f"  - {k}: [{steps}]")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    vendors_yaml = args.vendors or _default_path("templates/vendors.example.yaml")
    pipelines_yaml = args.pipelines or _default_path("templates/pipeline.example.yaml")

    vendor_sets = load_vendor_sets(vendors_yaml)
    pipelines = load_pipelines(pipelines_yaml)

    if args.vendor_set not in vendor_sets:
        print(f"ERROR: vendor_set '{args.vendor_set}' not found in {vendors_yaml}", file=sys.stderr)
        return 2
    if args.pipeline_id not in pipelines:
        print(f"ERROR: pipeline_id '{args.pipeline_id}' not found in {pipelines_yaml}", file=sys.stderr)
        return 2

    art = run_benchmark(
        vendor_set=vendor_sets[args.vendor_set],
        pipeline=pipelines[args.pipeline_id],
        catalog_path=args.catalog,
        testcases_path=args.testcases,
        vendors_yaml=vendors_yaml,
        pipelines_yaml=pipelines_yaml,
        out_dir=args.out_dir,
    )

    print(f"OK: run_id={art.run_id}")
    print(f"Artifacts: {art.out_dir}")
    print(f"- detail: {art.detail_jsonl_path}")
    print(f"- summary: {art.summary_json_path}")
    print(f"- report: {art.report_md_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ivhl", description="Intent Vector/Hybrid Lab CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="List vendor sets and pipelines")
    sp.add_argument("--vendors", help="vendors yaml path")
    sp.add_argument("--pipelines", help="pipelines yaml path")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("run", help="Run a pipeline benchmark")
    sp.add_argument("--pipeline-id", required=True)
    sp.add_argument("--vendor-set", required=True)
    sp.add_argument("--catalog", required=True)
    sp.add_argument("--testcases", required=True)
    sp.add_argument("--out-dir", default="runs")
    sp.add_argument("--vendors", help="vendors yaml path")
    sp.add_argument("--pipelines", help="pipelines yaml path")
    sp.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    rc = args.func(args)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
