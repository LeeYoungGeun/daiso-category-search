from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ivhl.core.types import Document, ScoredDoc


@dataclass
class FilterRules:
    min_score: float = 0.0
    deny_terms: List[str] = None
    hard_category_filter: bool = False


def apply_filters(
    scored: List[ScoredDoc],
    docs_by_id: dict[str, Document],
    *,
    rules: FilterRules,
    expected_category: str = "",
) -> List[ScoredDoc]:
    deny = [t for t in (rules.deny_terms or []) if t]
    out: List[ScoredDoc] = []
    for sd in scored:
        if rules.min_score and sd.score < rules.min_score:
            continue
        d = docs_by_id.get(sd.doc_id)
        if d is None:
            continue
        if rules.hard_category_filter and expected_category:
            if (d.category or "") != expected_category:
                continue
        if deny:
            hay = ((d.title or "") + " " + (d.text or "")).lower()
            if any(term.lower() in hay for term in deny):
                continue
        out.append(sd)
    return out
