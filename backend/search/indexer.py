"""
M1 Catalog Indexer
Indexes catalog TSV data into Elasticsearch (BM25) + Qdrant (Vector).

Usage:
    # From project root:
    python -m backend.search.indexer

    # Or with custom catalog:
    python -m backend.search.indexer --catalog poc/lyg/data/catalog.30cat.v3.tsv

    # Dry-run (no actual indexing):
    python -m backend.search.indexer --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# Ensure project root is in path
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.search.config import HybridSearchConfig
from backend.search.embedding import build_embedding_adapter


# ─── Constants ────────────────────────────────────────────────────────────────

ID_COL = "doc_id"
TITLE_COL = "title"
TEXT_COL = "text"
CAT_COL = "category"

DEFAULT_CATALOG = "poc/lyg/data/catalog.30cat.v3.tsv"
BATCH_SIZE = 50       # embedding batch size
BULK_CHUNK = 200      # elastic bulk chunk size

UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


# ─── Utilities ────────────────────────────────────────────────────────────────

def compact_space(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def build_bm25_text(title: str, text: str, category: str) -> str:
    """Build the text used for both BM25 indexing and embedding (fairness)."""
    return compact_space(f"{title} {text} {category}")


def docid_to_uuid(doc_id: str) -> str:
    """Stable UUID for Qdrant point ID."""
    return str(uuid.uuid5(UUID_NAMESPACE, doc_id))


def read_catalog(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Read TSV catalog file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Catalog not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


# ─── Elasticsearch Operations ─────────────────────────────────────────────────

class ElasticIndexer:
    def __init__(self, url: str, index: str, api_key: str = "", auth_header: str = ""):
        self.url = url.rstrip("/")
        self.index = index
        self.api_key = api_key
        self.auth_header = auth_header

    def _headers_json(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.auth_header:
            h["Authorization"] = self.auth_header
        elif self.api_key:
            h["Authorization"] = f"ApiKey {self.api_key}"
        return h

    def _headers_ndjson(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/x-ndjson"}
        json_h = self._headers_json()
        if "Authorization" in json_h:
            h["Authorization"] = json_h["Authorization"]
        return h

    def wait_ready(self, timeout: int = 60) -> bool:
        """Wait for Elasticsearch to be ready."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                r = requests.get(f"{self.url}/_cluster/health", headers=self._headers_json(), timeout=5)
                if r.status_code == 200:
                    print(f"  ✅ Elasticsearch ready ({self.url})")
                    return True
            except Exception:
                pass
            time.sleep(2)
        print(f"  ❌ Elasticsearch not ready after {timeout}s")
        return False

    def ensure_index(self) -> None:
        """Create index with mapping if it doesn't exist."""
        r = requests.head(f"{self.url}/{self.index}", headers=self._headers_json(), timeout=10)
        if r.status_code == 200:
            print(f"  ℹ️  Elastic index '{self.index}' already exists")
            return

        body = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "standard"},
                    "text": {"type": "text", "analyzer": "standard"},
                    "category": {"type": "keyword"},
                    "bm25_text": {"type": "text", "analyzer": "standard"},
                }
            },
        }
        r = requests.put(f"{self.url}/{self.index}", headers=self._headers_json(), json=body, timeout=30)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Create Elastic index failed: {r.status_code} {r.text}")
        print(f"  ✅ Elastic index '{self.index}' created")

    def delete_index(self) -> None:
        """Delete index if exists."""
        r = requests.delete(f"{self.url}/{self.index}", headers=self._headers_json(), timeout=10)
        if r.status_code in (200, 404):
            print(f"  🗑️  Elastic index '{self.index}' deleted")

    def bulk_index(self, docs: List[Dict[str, Any]]) -> int:
        """Bulk index documents. Returns count indexed."""
        if not docs:
            return 0
        lines = []
        for d in docs:
            _id = d["doc_id"]
            lines.append(json.dumps({"index": {"_index": self.index, "_id": _id}}, ensure_ascii=False))
            lines.append(json.dumps(d, ensure_ascii=False))
        payload = ("\n".join(lines) + "\n").encode("utf-8")

        r = requests.post(
            f"{self.url}/_bulk?refresh=true",
            headers=self._headers_ndjson(),
            data=payload,
            timeout=60,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Elastic bulk failed: {r.status_code} {r.text[:500]}")
        out = r.json()
        if out.get("errors"):
            items = out.get("items", [])
            bad = [it.get("index", {}).get("error") for it in items[:5] if it.get("index", {}).get("error")]
            raise RuntimeError(f"Elastic bulk errors: {bad}")
        return len(docs)

    def count(self) -> int:
        """Get document count in index."""
        try:
            r = requests.get(f"{self.url}/{self.index}/_count", headers=self._headers_json(), timeout=10)
            if r.status_code == 200:
                return r.json().get("count", 0)
        except Exception:
            pass
        return 0


# ─── Qdrant Operations ───────────────────────────────────────────────────────

class QdrantIndexer:
    def __init__(self, url: str, collection: str, api_key: str = ""):
        self.url = url.rstrip("/")
        self.collection = collection
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["api-key"] = self.api_key
        return h

    def wait_ready(self, timeout: int = 60) -> bool:
        """Wait for Qdrant to be ready."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                r = requests.get(f"{self.url}/healthz", headers=self._headers(), timeout=5)
                if r.status_code == 200:
                    print(f"  ✅ Qdrant ready ({self.url})")
                    return True
            except Exception:
                pass
            time.sleep(2)
        print(f"  ❌ Qdrant not ready after {timeout}s")
        return False

    def ensure_collection(self, vector_size: int) -> None:
        """Create collection if it doesn't exist."""
        r = requests.get(f"{self.url}/collections/{self.collection}", headers=self._headers(), timeout=10)
        if r.status_code == 200:
            print(f"  ℹ️  Qdrant collection '{self.collection}' already exists")
            return

        body = {"vectors": {"size": vector_size, "distance": "Cosine"}}
        r = requests.put(
            f"{self.url}/collections/{self.collection}",
            headers=self._headers(),
            json=body,
            timeout=30,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Create Qdrant collection failed: {r.status_code} {r.text}")
        print(f"  ✅ Qdrant collection '{self.collection}' created (dim={vector_size})")

    def delete_collection(self) -> None:
        """Delete collection if exists."""
        r = requests.delete(f"{self.url}/collections/{self.collection}", headers=self._headers(), timeout=10)
        if r.status_code in (200, 404):
            print(f"  🗑️  Qdrant collection '{self.collection}' deleted")

    def upsert(self, points: List[Dict[str, Any]]) -> int:
        """Upsert points. Returns count upserted."""
        if not points:
            return 0
        body = {"points": points}
        r = requests.put(
            f"{self.url}/collections/{self.collection}/points?wait=true",
            headers=self._headers(),
            json=body,
            timeout=60,
        )
        if r.status_code not in (200, 202):
            raise RuntimeError(f"Qdrant upsert failed: {r.status_code} {r.text[:500]}")
        return len(points)

    def count(self) -> int:
        """Get point count in collection."""
        try:
            r = requests.get(f"{self.url}/collections/{self.collection}", headers=self._headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                return data.get("result", {}).get("points_count", 0)
        except Exception:
            pass
        return 0


# ─── Main Indexing Logic ──────────────────────────────────────────────────────

def index_catalog(
    catalog_path: str = DEFAULT_CATALOG,
    config: Optional[HybridSearchConfig] = None,
    clean: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Index catalog into Elasticsearch + Qdrant.

    Args:
        catalog_path: Path to catalog TSV file
        config: Search config (default: from env)
        clean: Delete existing index/collection before indexing
        dry_run: Only validate, don't actually index

    Returns:
        Summary dict with counts and timing
    """
    config = config or HybridSearchConfig.from_env()
    start_time = time.time()

    print("=" * 60)
    print("M1 Catalog Indexer")
    print("=" * 60)

    # ── Read catalog ──
    print(f"\n📂 Reading catalog: {catalog_path}")
    rows, headers = read_catalog(catalog_path)
    for col in (ID_COL, TITLE_COL, TEXT_COL, CAT_COL):
        if col not in headers:
            raise ValueError(f"Catalog missing column '{col}'. Headers={headers}")
    print(f"  📊 {len(rows)} documents, columns: {headers}")

    if dry_run:
        print("\n🔍 Dry-run mode — validating only")
        valid = 0
        for r in rows:
            doc_id = (r.get(ID_COL) or "").strip()
            text = (r.get(TEXT_COL) or "").strip()
            if doc_id and text:
                valid += 1
        print(f"  ✅ {valid}/{len(rows)} valid documents")
        return {"status": "dry_run", "valid": valid, "total": len(rows)}

    # ── Initialize services ──
    print(f"\n🔧 Initializing services...")
    print(f"  Elasticsearch: {config.elastic.url}/{config.elastic.index}")
    print(f"  Qdrant: {config.qdrant.url}/{config.qdrant.collection}")
    print(f"  Embedding: {config.embedding.provider}/{config.embedding.model}")

    elastic = ElasticIndexer(
        url=config.elastic.url,
        index=config.elastic.index,
        api_key=config.elastic.api_key,
        auth_header=config.elastic.auth_header,
    )
    qdrant = QdrantIndexer(
        url=config.qdrant.url,
        collection=config.qdrant.collection,
        api_key=config.qdrant.api_key,
    )
    embedder = build_embedding_adapter(
        provider=config.embedding.provider,
        model=config.embedding.model,
        api_key=config.embedding.api_key,
        output_dimensionality=config.embedding.output_dimensionality,
    )

    # ── Wait for services ──
    print(f"\n⏳ Waiting for services...")
    if not elastic.wait_ready(timeout=30):
        raise RuntimeError("Elasticsearch not available")
    if not qdrant.wait_ready(timeout=30):
        raise RuntimeError("Qdrant not available")

    # ── Clean if requested ──
    if clean:
        print(f"\n🗑️  Cleaning existing data...")
        elastic.delete_index()
        qdrant.delete_collection()

    # ── Probe embedding dimension ──
    print(f"\n🔬 Probing embedding dimension...")
    sample_text = build_bm25_text(
        rows[0][TITLE_COL], rows[0][TEXT_COL], rows[0][CAT_COL]
    )
    sample_vec = embedder.embed_query(sample_text)
    dim = len(sample_vec)
    print(f"  📐 Embedding dimension: {dim}")

    # ── Ensure storage ──
    print(f"\n📦 Ensuring storage...")
    elastic.ensure_index()
    qdrant.ensure_collection(dim)

    # ── Index documents ──
    print(f"\n📥 Indexing {len(rows)} documents...")
    elastic_buf: List[Dict[str, Any]] = []
    sent_elastic = 0
    sent_qdrant = 0
    skipped = 0

    for i in range(0, len(rows), BATCH_SIZE):
        chunk = rows[i : i + BATCH_SIZE]

        ids: List[str] = []
        embed_inputs: List[str] = []
        q_payloads: List[Dict[str, Any]] = []

        for r in chunk:
            doc_id = (r.get(ID_COL) or "").strip()
            title = (r.get(TITLE_COL) or "").strip()
            text = (r.get(TEXT_COL) or "").strip()
            cat = (r.get(CAT_COL) or "").strip()

            if not doc_id or not text:
                skipped += 1
                continue

            bm25_text = build_bm25_text(title, text, cat)

            # Elastic doc
            elastic_buf.append({
                "doc_id": doc_id,
                "title": title,
                "text": text,
                "category": cat,
                "bm25_text": bm25_text,
            })

            # Qdrant: UUID id, original doc_id in payload
            qid = docid_to_uuid(doc_id)
            ids.append(qid)
            embed_inputs.append(bm25_text)
            q_payloads.append({
                "doc_id": doc_id,
                "title": title,
                "text": text,
                "category": cat,
                "bm25_text": bm25_text,
            })

        # Flush elastic in chunks
        while len(elastic_buf) >= BULK_CHUNK:
            batch_docs = elastic_buf[:BULK_CHUNK]
            elastic_buf = elastic_buf[BULK_CHUNK:]
            sent_elastic += elastic.bulk_index(batch_docs)

        # Qdrant: embed + upsert
        if ids:
            vecs = embedder.embed_texts(embed_inputs)
            points = [
                {"id": qid, "vector": v, "payload": pl}
                for qid, v, pl in zip(ids, vecs, q_payloads)
            ]
            sent_qdrant += qdrant.upsert(points)

        progress = min(i + BATCH_SIZE, len(rows))
        print(f"  [{progress}/{len(rows)}] elastic={sent_elastic} qdrant={sent_qdrant} skipped={skipped}")

    # Flush remaining elastic
    if elastic_buf:
        sent_elastic += elastic.bulk_index(elastic_buf)

    elapsed = time.time() - start_time

    # ── Verify ──
    print(f"\n✅ Indexing complete!")
    print(f"  Elasticsearch: {elastic.count()} docs in '{config.elastic.index}'")
    print(f"  Qdrant: {qdrant.count()} points in '{config.qdrant.collection}'")
    print(f"  Skipped: {skipped}")
    print(f"  Time: {elapsed:.1f}s")

    summary = {
        "status": "ok",
        "elastic_indexed": sent_elastic,
        "qdrant_indexed": sent_qdrant,
        "skipped": skipped,
        "total_rows": len(rows),
        "embedding_dim": dim,
        "elapsed_seconds": round(elapsed, 1),
    }
    print(f"\n📊 Summary: {json.dumps(summary, indent=2)}")
    return summary


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="M1 Catalog Indexer")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="Path to catalog TSV")
    parser.add_argument("--clean", action="store_true", help="Delete existing data before indexing")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, don't index")
    args = parser.parse_args()

    # Load .env if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    index_catalog(
        catalog_path=args.catalog,
        clean=args.clean,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
