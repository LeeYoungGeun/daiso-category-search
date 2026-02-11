from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from ivhl.adapters.bm25 import LocalBM25, ElasticBM25Retriever
from ivhl.adapters.embedding import build_embedding_adapter
from ivhl.adapters.filtering import FilterRules, apply_filters
from ivhl.adapters.fusion import rrf_fusion, weighted_fusion
from ivhl.adapters.rerank import build_reranker
from ivhl.adapters.retrieval import BruteForceVectorRetriever, QdrantVectorRetriever
from ivhl.core.config import PipelineSpec, VendorSet
from ivhl.core.io import load_catalog_tsv, load_testcases_tsv
from ivhl.core.metrics import aggregate, mrr, ndcg_at_k, precision_at_k, recall_at_k
from ivhl.core.runlog import RunLogger, write_json
from ivhl.core.types import Document, RunArtifacts, ScoredDoc


def _mk_run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def prepare_run(out_dir: str | Path, *, run_id: str | None = None) -> RunArtifacts:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rid = run_id or _mk_run_id()
    run_root = out / rid
    run_root.mkdir(parents=True, exist_ok=True)
    return RunArtifacts(
        run_id=rid,
        out_dir=str(run_root),
        detail_jsonl_path=str(run_root / "detail.jsonl"),
        summary_json_path=str(run_root / "summary.json"),
        report_md_path=str(run_root / "report.md"),
    )


def _copy_configs(art: RunArtifacts, *, vendor_path: str | Path, pipeline_path: str | Path) -> None:
    run_root = Path(art.out_dir)
    cfg_dir = run_root / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    vp = Path(vendor_path)
    pp = Path(pipeline_path)
    if vp.exists():
        dst = cfg_dir / vp.name
        shutil.copy2(vp, dst)
        art.copied_configs["vendors"] = str(dst)
    if pp.exists():
        dst = cfg_dir / pp.name
        shutil.copy2(pp, dst)
        art.copied_configs["pipelines"] = str(dst)


def _docs_by_id(docs: List[Document]) -> Dict[str, Document]:
    return {d.doc_id: d for d in docs}


def _assert_bm25_only_config(_vendor_set: VendorSet, pipeline: PipelineSpec) -> None:
    # bm25_only는 "dense/fusion/rerank 금지"만 강제한다.
    if pipeline.pipeline_id != "bm25_only":
        return
    forbidden = {"dense", "fusion", "rerank"}
    bad = forbidden.intersection(set(pipeline.steps))
    if bad:
        raise RuntimeError(f"[GUARD] bm25_only인데 금지 step 포함: {sorted(bad)} / steps={pipeline.steps}")
    if "bm25" not in pipeline.steps:
        raise RuntimeError(f"[GUARD] bm25_only인데 steps에 bm25가 없음: steps={pipeline.steps}")


def _pick_text(*cands: str) -> str:
    for x in cands:
        if (x or "").strip():
            return x.strip()
    return ""


def _get_env(cfg: Dict[str, Any], key: str, default: str = "") -> str:
    env_key = (cfg.get(key) or "").strip()
    if not env_key:
        return default
    return (os.environ.get(env_key) or "").strip()  # type: ignore[name-defined]


def run_benchmark(
    *,
    vendor_set: VendorSet,
    pipeline: PipelineSpec,
    catalog_path: str | Path,
    testcases_path: str | Path,
    vendors_yaml: str | Path,
    pipelines_yaml: str | Path,
    out_dir: str | Path,
) -> RunArtifacts:
    import os  # local import to avoid accidental shadowing above

    load_dotenv()

    art = prepare_run(out_dir)
    logger = RunLogger(art.detail_jsonl_path)

    docs = load_catalog_tsv(catalog_path)
    cases = load_testcases_tsv(testcases_path)
    docs_map = _docs_by_id(docs)

    _assert_bm25_only_config(vendor_set, pipeline)

    use_dense = "dense" in pipeline.steps
    use_bm25 = "bm25" in pipeline.steps

    if "fusion" in pipeline.steps and not (use_dense and use_bm25):
        raise RuntimeError(f"[GUARD] fusion은 dense+bm25 둘 다 필요: steps={pipeline.steps}")

    # ---- Build embedding (query embedding always needed for dense)
    embedding = None
    embed_docs_ms = 0.0

    # ---- Build vector retriever (local brute-force OR qdrant)
    vec_retriever: Optional[Any] = None

    if use_dense:
        emb_cfg = (vendor_set.config.get("embedding") or {"provider": "mock"})
        embedding = build_embedding_adapter(emb_cfg)

        vdb_cfg = (vendor_set.config.get("vector_db") or {"provider": "local"})
        vdb_provider = (vdb_cfg.get("provider") or "local").lower()

        if vdb_provider == "qdrant":
            qdrant_url = (os.environ.get(vdb_cfg.get("endpoint_env") or "") or "").strip()
            qdrant_key = (os.environ.get(vdb_cfg.get("api_key_env") or "") or "").strip()
            collection = (vdb_cfg.get("index") or "products").strip()
            if not qdrant_url:
                raise RuntimeError("[GUARD] vector_db.provider=qdrant 인데 QDRANT_URL(env)이 비어있음")
            vec_retriever = QdrantVectorRetriever(url=qdrant_url, collection=collection, api_key=qdrant_key)
        else:
            # local brute-force: embed all docs once
            t0 = time.time()
            doc_texts = [(d.title + " " + d.text).strip() for d in docs]
            if hasattr(embedding, "embed_documents"):
                doc_vecs_list = embedding.embed_documents(doc_texts)  # type: ignore[attr-defined]
            else:
                doc_vecs_list = embedding.embed_texts(doc_texts)
            doc_vecs = {d.doc_id: v for d, v in zip(docs, doc_vecs_list)}
            embed_docs_ms = (time.time() - t0) * 1000
            vec_retriever = BruteForceVectorRetriever(docs=docs, doc_vecs=doc_vecs)

    # ---- Build BM25 retriever (local OR elastic)
    bm25_retriever: Optional[Any] = None
    if use_bm25:
        bm25_cfg = (vendor_set.config.get("bm25") or {"provider": "builtin"})
        bm25_provider = (bm25_cfg.get("provider") or "builtin").lower()

        if bm25_provider == "elastic":
            elastic_url = (os.environ.get(bm25_cfg.get("endpoint_env") or "") or "").strip()
            elastic_key = (os.environ.get(bm25_cfg.get("api_key_env") or "") or "").strip()
            index = (bm25_cfg.get("index") or "products").strip()
            if not elastic_url:
                raise RuntimeError("[GUARD] bm25.provider=elastic 인데 ELASTIC_URL(env)이 비어있음")
            bm25_retriever = ElasticBM25Retriever(docs=docs, base_url=elastic_url, index=index, api_key=elastic_key)
        else:
            bm25_retriever = LocalBM25(docs=docs)

    # ---- Optional reranker
    reranker = None
    if "rerank" in pipeline.steps:
        rerank_cfg = (vendor_set.config.get("rerank") or {"provider": "mock"})
        reranker = build_reranker(rerank_cfg)

    logger.log(
        "run_start",
        {
            "run_id": art.run_id,
            "vendor_set_id": vendor_set.vendor_set_id,
            "pipeline_id": pipeline.pipeline_id,
            "n_docs": len(docs),
            "n_cases": len(cases),
            "embed_docs_ms": embed_docs_ms,
        },
    )

    per_case_metrics: List[Dict[str, float]] = []
    n_skipped = 0
    n_bad_gold = 0

    for c in cases:
        intent_text = _pick_text(c.intent_text, c.raw_text)
        bm25_query_text = _pick_text(getattr(c, "bm25_query_text", "") or "", intent_text, c.raw_text)

        # ✅ 공정 비교: dense/bm25 모두 동일한 query_text 규칙 사용
        query_text_for_retrieval = bm25_query_text

        case_payload: Dict[str, Any] = {
            "case_id": c.case_id,
            "raw_text": c.raw_text,
            "intent_text": intent_text,
            "bm25_query_text": bm25_query_text,
            "expected_doc_ids": c.expected_doc_ids,
            "expected_category": c.expected_category,
            "needs_clarification": c.needs_clarification,
            "notes": c.notes,
            "pipeline": pipeline.pipeline_id,
            "vendor_set": vendor_set.vendor_set_id,
        }

        if c.needs_clarification:
            n_skipped += 1
            case_payload["status"] = "SKIPPED"
            logger.log("case", case_payload)
            continue

        if c.expected_doc_ids:
            missing = [x for x in c.expected_doc_ids if x not in docs_map]
            if missing:
                n_bad_gold += 1
                case_payload["status"] = "BAD_GOLD"
                case_payload["missing_expected_doc_ids"] = missing
                logger.log("case", case_payload)
                continue

        # ---- Dense
        embed_q_ms = 0.0
        dense_ms = 0.0
        dense: List[ScoredDoc] = []
        if use_dense:
            if embedding is None or vec_retriever is None:
                raise RuntimeError("[GUARD] use_dense=True인데 embedding/vec_retriever가 준비되지 않음")

            t1 = time.time()
            if hasattr(embedding, "embed_query"):
                qvec = embedding.embed_query(query_text_for_retrieval)  # type: ignore[attr-defined]
            else:
                qvec = embedding.embed_texts([query_text_for_retrieval])[0]
            embed_q_ms = (time.time() - t1) * 1000

            t2 = time.time()
            top_k_dense = int(pipeline.params.get("top_k_dense") or pipeline.params.get("top_k") or 50)
            dense = vec_retriever.query(qvec, top_k=top_k_dense)
            dense_ms = (time.time() - t2) * 1000

        # ---- BM25
        sparse: List[ScoredDoc] = []
        bm25_ms = 0.0
        if use_bm25:
            if bm25_retriever is None:
                raise RuntimeError("[GUARD] use_bm25=True인데 bm25_retriever가 None")
            t3 = time.time()
            top_k_bm25 = int(pipeline.params.get("top_k_bm25") or 50)
            sparse = bm25_retriever.query(bm25_query_text, top_k=top_k_bm25)
            bm25_ms = (time.time() - t3) * 1000
            case_payload["top5_bm25_doc_ids"] = [sd.doc_id for sd in sparse[:5]]

        # ---- Fusion (Hybrid)
        if "fusion" in pipeline.steps:
            fusion_cfg = pipeline.params.get("fusion") or {}
            method = (fusion_cfg.get("method") or "rrf").lower()
            top_k_fused = int(pipeline.params.get("top_k_fused") or 50)
            if method == "rrf":
                fused = rrf_fusion(dense, sparse, rrf_k=int(fusion_cfg.get("rrf_k") or 60), top_k=top_k_fused)
            else:
                alpha = float(fusion_cfg.get("alpha") or pipeline.params.get("alpha") or 0.5)
                fused = weighted_fusion(dense, sparse, alpha=alpha, top_k=top_k_fused)
        else:
            fused = dense if use_dense else sparse

        # ---- Rerank
        reranked = fused
        rerank_ms = 0.0
        if "rerank" in pipeline.steps:
            if reranker is None:
                raise RuntimeError("[GUARD] rerank step인데 reranker가 None")
            t4 = time.time()
            rerank_top_k = int(pipeline.params.get("rerank_top_k") or 20)
            candidate_ids = [sd.doc_id for sd in fused[:rerank_top_k]]
            candidate_docs = [docs_map[i] for i in candidate_ids if i in docs_map]
            reranked = reranker.rerank(query_text_for_retrieval, candidate_docs, top_k=len(candidate_docs))
            rerank_ms = (time.time() - t4) * 1000

        # ---- Filter
        final = reranked
        if "filter" in pipeline.steps:
            filt = pipeline.params.get("filter") or {}
            rules = FilterRules(
                min_score=float(filt.get("min_score") or 0.0),
                deny_terms=list(filt.get("deny_terms") or []),
                hard_category_filter=bool(filt.get("hard_category_filter") or False),
            )
            final = apply_filters(final, docs_map, rules=rules, expected_category=c.expected_category)

        pred_ids = [sd.doc_id for sd in final]
        case_payload["top5_doc_ids"] = pred_ids[:5]

        cm = None
        if c.expected_doc_ids:
            cm = {
                "precision@10": precision_at_k(pred_ids, c.expected_doc_ids, 10),
                "recall@10": recall_at_k(pred_ids, c.expected_doc_ids, 10),
                "mrr": mrr(pred_ids, c.expected_doc_ids),
                "ndcg@10": ndcg_at_k(pred_ids, c.expected_doc_ids, 10),
            }
            per_case_metrics.append(cm)

        case_payload.update(
            {
                "status": "EVAL",
                "predicted_doc_ids": pred_ids[:50],
                "stage_counts": {
                    "dense": len(dense),
                    "bm25": len(sparse),
                    "fused": len(fused),
                    "rerank": len(reranked),
                    "final": len(final),
                },
                "latency_ms": {
                    "embed_query": embed_q_ms,
                    "dense_retrieval": dense_ms,
                    "bm25": bm25_ms,
                    "rerank": rerank_ms,
                },
                "metrics": cm,
            }
        )
        logger.log("case", case_payload)

    summary = aggregate(per_case_metrics)

    summary_obj: Dict[str, Any] = {
        "run_id": art.run_id,
        "vendor_set_id": vendor_set.vendor_set_id,
        "pipeline_id": pipeline.pipeline_id,
        "n_docs": len(docs),
        "n_cases": len(cases),
        "n_eval": summary.n_eval,
        "n_skipped": n_skipped,
        "n_bad_gold": n_bad_gold,
        "metrics": summary.as_dict() if summary.n_eval > 0 else None,
    }

    write_json(art.summary_json_path, summary_obj)

    report = f"""# Intent Vector/Hybrid Lab Report

- Run ID: `{art.run_id}`
- Vendor Set: `{vendor_set.vendor_set_id}`
- Pipeline: `{pipeline.pipeline_id}`
- Docs: {len(docs)}
- Cases: {len(cases)} (eval={summary.n_eval}, skipped={n_skipped}, bad_gold={n_bad_gold})

## Metrics (mean)

{"(no metrics)" if summary.n_eval == 0 else f"""| Metric | Value |
|---|---:|
| Precision@10 | {summary_obj['metrics']['precision@10']:.4f} |
| Recall@10 | {summary_obj['metrics']['recall@10']:.4f} |
| MRR | {summary_obj['metrics']['mrr']:.4f} |
| nDCG@10 | {summary_obj['metrics']['ndcg@10']:.4f} |"""}

## Artifacts

- detail: `{Path(art.detail_jsonl_path).name}`
- summary: `{Path(art.summary_json_path).name}`
"""
    Path(art.report_md_path).write_text(report, encoding="utf-8")

    _copy_configs(art, vendor_path=vendors_yaml, pipeline_path=pipelines_yaml)

    logger.log("run_end", summary_obj)
    return art
