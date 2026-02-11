# scripts/run_benchmark.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML 파일을 찾을 수 없습니다: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def import_run_benchmark():
    """
    프로젝트 구조가 바뀌어도 최대한 자동으로 run_benchmark를 찾습니다.
    1) ivhl.core.pipeline
    2) ivhl.pipeline
    (필요하면 후보를 더 추가)
    """
    last_err = None
    for mod_path in ("ivhl.core.pipeline", "ivhl.pipeline"):
        try:
            mod = __import__(mod_path, fromlist=["run_benchmark"])
            return getattr(mod, "run_benchmark")
        except Exception as e:
            last_err = e
    raise ImportError(
        "run_benchmark import 실패. 아래 후보 모듈에서 찾지 못했습니다: "
        "ivhl.core.pipeline, ivhl.pipeline\n"
        f"마지막 에러: {last_err}\n"
        "해결: (1) 패키지/모듈 경로 확인 (2) venv에서 프로젝트 editable 설치 여부 확인"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--vendors", required=True)
    p.add_argument("--pipelines", required=True)
    p.add_argument("--vendor-set", required=True, dest="vendor_set")
    p.add_argument("--pipeline", required=True)
    p.add_argument("--catalog", required=True)
    p.add_argument("--testcases", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    vendors_cfg = load_yaml(args.vendors)
    pipelines_cfg = load_yaml(args.pipelines)

    if "vendor_sets" not in vendors_cfg:
        raise KeyError("vendors yaml에 'vendor_sets' 키가 없습니다.")
    if "pipelines" not in pipelines_cfg:
        raise KeyError("pipelines yaml에 'pipelines' 키가 없습니다.")

    if args.vendor_set not in vendors_cfg["vendor_sets"]:
        raise KeyError(f"vendors yaml에 vendor_set '{args.vendor_set}' 이(가) 없습니다.")
    if args.pipeline not in pipelines_cfg["pipelines"]:
        raise KeyError(f"pipelines yaml에 pipeline '{args.pipeline}' 이(가) 없습니다.")

    vs_cfg = vendors_cfg["vendor_sets"][args.vendor_set]
    pl_cfg = pipelines_cfg["pipelines"][args.pipeline]

    # out dir 보장
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 여기부터는 프로젝트 내부 타입을 쓰는 구조면 그대로 유지
    # (VendorSet / PipelineSpec 위치도 프로젝트마다 다를 수 있어,
    #  필요시 이 부분도 import 자동탐색으로 바꿔야 합니다.)
    from ivhl.core.config import PipelineSpec, VendorSet  # 구조가 다르면 여기서 ImportError

    vendor_set = VendorSet(vendor_set_id=args.vendor_set, config=vs_cfg)
    pipeline = PipelineSpec(
        pipeline_id=pl_cfg.get("pipeline_id", args.pipeline),
        steps=pl_cfg.get("steps", []),
        params=pl_cfg.get("params", {}),
    )

    run_benchmark = import_run_benchmark()

    art = run_benchmark(
        vendor_set=vendor_set,
        pipeline=pipeline,
        catalog_path=args.catalog,
        testcases_path=args.testcases,
        vendors_yaml=args.vendors,
        pipelines_yaml=args.pipelines,
        out_dir=str(out_dir),
    )
    print("DONE:", getattr(art, "out_dir", out_dir))


if __name__ == "__main__":
    main()
