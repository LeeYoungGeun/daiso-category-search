from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Document:
    doc_id: str
    title: str
    text: str
    category: str = ""
    meta: Dict[str, str] = field(default_factory=dict)


@dataclass
class QueryCase:
    case_id: str
    raw_text: str
    intent_text: str
    expected_doc_ids: List[str] = field(default_factory=list)  # ✅ gold doc_id list
    bm25_query_text: str = ""  # ✅ BM25 input (expanded keywords)
    expected_category: str = ""
    needs_clarification: bool = False
    notes: str = ""


@dataclass
class ScoredDoc:
    doc_id: str
    score: float
    source: str = ""   # ✅ 추가 (dense/bm25/fused 등 표시용)
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunArtifacts:
    run_id: str
    out_dir: str
    detail_jsonl_path: str
    summary_json_path: str
    report_md_path: str
    copied_configs: Dict[str, str] = field(default_factory=dict)
