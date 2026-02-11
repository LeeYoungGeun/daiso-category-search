from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List

from ivhl.core.types import Document, QueryCase


def _iter_tsv_rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        raw = f.read().splitlines()

    header_idx = None
    header_line = None
    for i, line in enumerate(raw):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            cand = line.lstrip()[1:].strip()
            if "\t" in cand:
                header_idx = i
                header_line = cand
                break
            continue
        header_idx = i
        header_line = line
        break

    if header_idx is None or header_line is None:
        return []

    reader = csv.DictReader(raw[header_idx + 1 :], fieldnames=header_line.split("\t"), delimiter="\t")
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        first_key = next(iter(row.keys()))
        if (row.get(first_key) or "").lstrip().startswith("#"):
            continue
        yield {k: (v or "").strip() for k, v in row.items()}


def _parse_id_list(s: str) -> List[str]:
    s = (s or "").strip()
    if not s:
        return []
    # allow "a|b|c" or "a,b,c"
    s = s.replace(",", "|")
    parts = [p.strip() for p in s.split("|")]
    return [p for p in parts if p]


def load_catalog_tsv(path: str | Path) -> List[Document]:
    p = Path(path)
    docs: List[Document] = []
    for row in _iter_tsv_rows(p):
        doc_id = row.get("doc_id") or row.get("id") or row.get("docid") or ""
        if not doc_id:
            continue
        title = row.get("title", "")
        text = row.get("text") or row.get("body") or row.get("content") or ""
        category = row.get("category", "")
        meta = {k: v for k, v in row.items() if k not in {"doc_id", "id", "docid", "title", "text", "body", "content", "category"}}
        docs.append(Document(doc_id=doc_id, title=title, text=text, category=category, meta=meta))
    return docs


def load_testcases_tsv(path: str | Path) -> List[QueryCase]:
    p = Path(path)
    cases: List[QueryCase] = []
    for row in _iter_tsv_rows(p):
        case_id = row.get("id") or row.get("case_id") or row.get("qid") or ""
        if not case_id:
            continue

        raw_text = row.get("raw_text", "")
        intent_text = row.get("intent_text", "")

        # ✅ gold labels
        expected_doc_ids = _parse_id_list(row.get("expected_doc_ids", ""))

        expected_category = row.get("expected_category", "")
        needs_clarification = (row.get("needs_clarification", "").lower() in {"true", "1", "yes", "y"})
        notes = row.get("notes", "")

        # ✅ BM25 input text (expanded keywords)
        bm25_query_text = row.get("bm25_query_text", "")

        cases.append(
            QueryCase(
                case_id=case_id,
                raw_text=raw_text,
                intent_text=intent_text,
                expected_doc_ids=expected_doc_ids,
                bm25_query_text=bm25_query_text,
                expected_category=expected_category,
                needs_clarification=needs_clarification,
                notes=notes,
            )
        )
    return cases
