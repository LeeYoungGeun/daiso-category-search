from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


@dataclass(frozen=True)
class VendorSet:
    vendor_set_id: str
    config: Dict[str, Any]


@dataclass(frozen=True)
class PipelineSpec:
    pipeline_id: str
    steps: list[str]
    params: Dict[str, Any]


def load_vendor_sets(vendors_yaml: str | Path) -> Dict[str, VendorSet]:
    data = load_yaml(vendors_yaml)
    vs = data.get("vendor_sets") or {}
    out: Dict[str, VendorSet] = {}
    for k, v in vs.items():
        out[str(k)] = VendorSet(vendor_set_id=str(k), config=v or {})
    return out


def load_pipelines(pipelines_yaml: str | Path) -> Dict[str, PipelineSpec]:
    data = load_yaml(pipelines_yaml)
    pls = data.get("pipelines") or {}
    out: Dict[str, PipelineSpec] = {}
    for pid, cfg in pls.items():
        steps = list(cfg.get("steps") or [])
        params = cfg.get("params") or {}
        out[str(pid)] = PipelineSpec(pipeline_id=str(pid), steps=steps, params=params)
    return out
