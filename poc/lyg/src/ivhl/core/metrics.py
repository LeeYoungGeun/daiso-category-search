# src/ivhl/core/metrics.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence


def precision_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    if k <= 0:
        return 0.0
    gold = set(gold_ids or [])
    topk = list(pred_ids)[:k]
    hit = sum(1 for x in topk if x in gold)
    # ✅ 분모는 항상 k로 고정 (비교 가능)
    return hit / float(k)


def recall_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    gold = set(gold_ids or [])
    if not gold:
        return 0.0
    topk = list(pred_ids)[:k]
    hit = sum(1 for x in topk if x in gold)
    return hit / float(len(gold))


def mrr(pred_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
    gold = set(gold_ids or [])
    if not gold:
        return 0.0
    for i, x in enumerate(pred_ids):
        if x in gold:
            return 1.0 / float(i + 1)
    return 0.0


def ndcg_at_k(pred_ids: Sequence[str], gold_ids: Sequence[str], k: int) -> float:
    gold = set(gold_ids or [])
    if not gold or k <= 0:
        return 0.0
    topk = list(pred_ids)[:k]
    # binary relevance
    dcg = 0.0
    for i, x in enumerate(topk):
        rel = 1.0 if x in gold else 0.0
        if rel > 0:
            dcg += 1.0 / ( (i + 1) ** 0.5 )  # 간단한 할인(프로젝트 기존 구현이 있으면 그걸 유지해도 됨)
    # ideal dcg (all ones)
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / ((i + 1) ** 0.5) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


@dataclass
class Summary:
    n_eval: int
    metrics: Dict[str, float]

    def as_dict(self) -> Dict[str, float]:
        return dict(self.metrics)


def aggregate(per_case: List[Dict[str, float]]) -> Summary:
    if not per_case:
        return Summary(n_eval=0, metrics={"precision@10": 0.0, "recall@10": 0.0, "mrr": 0.0, "ndcg@10": 0.0})
    keys = per_case[0].keys()
    out: Dict[str, float] = {}
    for k in keys:
        out[k] = sum(x.get(k, 0.0) for x in per_case) / float(len(per_case))
    return Summary(n_eval=len(per_case), metrics=out)
