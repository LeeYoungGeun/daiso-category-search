"""
Hybrid Fair Indexing (BM25 + Dense) for your current TSV schema.

Inputs:
- catalog.30cat.v3.tsv : columns [doc_id, title, text, category]
- testcases.v6.tsv     : column expected_doc_ids (comma-separated)

Outputs:
- Qdrant collection (default: products) with:
  - id = doc_id
  - vector = embedding(bm25_text)   # IMPORTANT: same text as BM25 indexing for fairness
  - payload includes title/text/category/bm25_text

- Elastic index (default: products) with:
  - _id = doc_id
  - fields: title, text, category, bm25_text

Fairness rule:
- bm25_text is identical input used for BOTH bm25 indexing and dense embedding.

Required env:
- OPENAI_API_KEY
- QDRANT_URL
- ELASTIC_URL

Optional env:
- QDRANT_API_KEY
- ELASTIC_API_KEY  (if your elastic requires key; otherwise can be empty)
- QDRANT_COLLECTION (default: products)
- ELASTIC_INDEX     (default: products)
- EMBED_MODEL       (default: text-embedding-3-small)
- CATALOG_TSV       (default: data/catalog.30cat.v3.tsv)
- TESTCASES_TSV     (default: templates/testcases.v6.tsv)
- BATCH             (default: 128)
- BULK_CHUNK        (default: 500)  # elastic bulk docs per request
- TEXT_TEMPLATE     (default: "{title} {text} {category}")  # to build bm25_text
"""

import os, csv, time, json, re
from typing import Dict, List, Any, Tuple, Optional

import requests
from openai import OpenAI

# -----------------------------
# ENV
# -----------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
QDRANT_URL = os.environ.get("QDRANT_URL", "").strip().rstrip("/")
ELASTIC_URL = os.environ.get("ELASTIC_URL", "").strip().rstrip("/")

if not OPENAI_API_KEY:
    raise SystemExit("Missing env OPENAI_API_KEY")
if not QDRANT_URL:
    raise SystemExit("Missing env QDRANT_URL")
if not ELASTIC_URL:
    raise SystemExit("Missing env ELASTIC_URL")

QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "").strip()
ELASTIC_API_KEY = os.environ.get("ELASTIC_API_KEY", "").strip()

QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "products").strip()
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "products").strip()

EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small").strip()

CATALOG_TSV = os.environ.get("CATALOG_TSV", "data/catalog.30cat.v3.tsv")
TESTCASES_TSV = os.environ.get("TESTCASES_TSV", "templates/testcases.v6.tsv")

BATCH = int(os.environ.get("BATCH", "128"))
BULK_CHUNK = int(os.environ.get("BULK_CHUNK", "500"))

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
MAX_RETRY = int(os.environ.get("MAX_RETRY", "5"))
RETRY_SLEEP_BASE = float(os.environ.get("RETRY_SLEEP_BASE", "1.5"))

# Your catalog columns (fixed)
ID_COL = "doc_id"
TITLE_COL = "title"
TEXT_COL = "text"
CAT_COL = "category"

# IMPORTANT: same text used by BM25 and Dense for fairness
TEXT_TEMPLATE = os.environ.get("TEXT_TEMPLATE", "{title} {text} {category}")

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# Utilities
# -----------------------------
def read_tsv(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    if not os.path.exists(path):
        return [], []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        return rows, reader.fieldnames or []

def parse_expected_doc_ids(s: str) -> List[str]:
    if not s:
        return []
    raw = s.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            arr = json.loads(raw.replace("'", '"'))
            return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    return [p.strip() for p in re.split(r"[,\|]", raw) if p.strip()]

def compact_space(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def build_bm25_text(title: str, text: str, category: str) -> str:
    # For fairness: identical text goes to BM25 index and embedding input.
    title = compact_space(title)
    text = compact_space(text)
    category = compact_space(category)
    out = TEXT_TEMPLATE.format(title=title, text=text, category=category)
    out = compact_space(out)
    return out

# -----------------------------
# Qdrant
# -----------------------------
def qdrant_headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if QDRANT_API_KEY:
        h["api-key"] = QDRANT_API_KEY
    return h

def http_retry(method: str, url: str, *, headers: Dict[str, str], json_body: Any = None, data: Any = None) -> requests.Response:
    last_exc = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                data=data,
                timeout=HTTP_TIMEOUT,
            )
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(RETRY_SLEEP_BASE * attempt)
                continue
            return r
        except Exception as e:
            last_exc = e
            time.sleep(RETRY_SLEEP_BASE * attempt)
    raise RuntimeError(f"HTTP failed after retries: {url} / last_exc={last_exc}")

def ensure_qdrant_collection(vector_size: int):
    r = http_retry("GET", f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", headers=qdrant_headers())
    if r.status_code == 200:
        return
    body = {"vectors": {"size": vector_size, "distance": "Cosine"}}
    cr = http_retry("PUT", f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", headers=qdrant_headers(), json_body=body)
    if cr.status_code not in (200, 201):
        raise RuntimeError(f"Create Qdrant collection failed: {cr.status_code} {cr.text}")

def qdrant_upsert(points: List[Dict[str, Any]]):
    body = {"points": points}
    r = http_retry(
        "PUT",
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true",
        headers=qdrant_headers(),
        json_body=body,
    )
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Qdrant upsert failed: {r.status_code} {r.text}")

# -----------------------------
# Elastic
# -----------------------------
def elastic_headers() -> Dict[str, str]:
    h = {"Content-Type": "application/x-ndjson"}
    if ELASTIC_API_KEY:
        # Common patterns: ApiKey <base64> OR Bearer <token>
        # If you store a ready-to-use header value, set ELASTIC_AUTH_HEADER instead.
        auth_header = os.environ.get("ELASTIC_AUTH_HEADER", "").strip()
        if auth_header:
            h["Authorization"] = auth_header
        else:
            # fallback: assume ApiKey
            h["Authorization"] = f"ApiKey {ELASTIC_API_KEY}"
    return h

def ensure_elastic_index():
    # If exists -> ok
    r = http_retry("HEAD", f"{ELASTIC_URL}/{ELASTIC_INDEX}", headers={"Content-Type": "application/json", **(elastic_headers() or {})})
    if r.status_code == 200:
        return

    # Create with a simple mapping (BM25 default)
    # analyzer: standard is fine for a baseline; you can tune later.
    body = {
        "mappings": {
            "properties": {
                "doc_id": {"type": "keyword"},
                "title": {"type": "text"},
                "text": {"type": "text"},
                "category": {"type": "keyword"},
                "bm25_text": {"type": "text"},
            }
        }
    }
    cr = http_retry("PUT", f"{ELASTIC_URL}/{ELASTIC_INDEX}", headers={"Content-Type": "application/json"}, json_body=body)
    if cr.status_code not in (200, 201):
        raise RuntimeError(f"Create Elastic index failed: {cr.status_code} {cr.text}")

def elastic_bulk(docs: List[Dict[str, Any]]):
    # NDJSON: action line + source line
    lines = []
    for d in docs:
        _id = d["doc_id"]
        lines.append(json.dumps({"index": {"_index": ELASTIC_INDEX, "_id": _id}}, ensure_ascii=False))
        lines.append(json.dumps(d, ensure_ascii=False))
    payload = "\n".join(lines) + "\n"

    r = http_retry("POST", f"{ELASTIC_URL}/_bulk?refresh=true", headers=elastic_headers(), data=payload.encode("utf-8"))
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Elastic bulk failed: {r.status_code} {r.text}")

    out = r.json()
    if out.get("errors"):
        # print first few errors
        items = out.get("items", [])
        bad = []
        for it in items:
            idx = it.get("index") or {}
            if idx.get("error"):
                bad.append(idx.get("error"))
                if len(bad) >= 5:
                    break
        raise RuntimeError(f"Elastic bulk returned errors. Example errors: {bad}")

# -----------------------------
# Embedding
# -----------------------------
def embed_texts(texts: List[str]) -> List[List[float]]:
    last_exc = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as e:
            last_exc = e
            time.sleep(RETRY_SLEEP_BASE * attempt)
    raise RuntimeError(f"Embedding failed after retries: {last_exc}")

# -----------------------------
# Main
# -----------------------------
def main():
    catalog_rows, headers = read_tsv(CATALOG_TSV)
    if not catalog_rows:
        raise SystemExit(f"Catalog TSV not found or empty: {CATALOG_TSV}")

    for col in (ID_COL, TITLE_COL, TEXT_COL, CAT_COL):
        if col not in headers:
            raise SystemExit(f"Catalog missing column '{col}'. Headers={headers}")

    # Validate expected_doc_ids are present
    test_rows, test_headers = read_tsv(TESTCASES_TSV)
    if test_rows and "expected_doc_ids" in test_headers:
        catalog_ids = set((r.get(ID_COL) or "").strip() for r in catalog_rows if (r.get(ID_COL) or "").strip())
        missing = []
        for tr in test_rows:
            for did in parse_expected_doc_ids(tr.get("expected_doc_ids") or ""):
                if did and did not in catalog_ids:
                    missing.append(did)
        missing = sorted(set(missing))
        if missing:
            print(f"[WARN] Missing expected_doc_ids not found in catalog ({len(missing)}):")
            print("       " + ", ".join(missing[:50]) + (" ..." if len(missing) > 50 else ""))
            print("[WARN] 이 상태면 평가가 오답 처리될 수 있습니다. doc_id를 통일하세요.")
    else:
        print(f"[INFO] Skip testcases validation (file missing or header missing): {TESTCASES_TSV}")

    # Build one sample embedding to get dim
    s0 = catalog_rows[0]
    bm25_text0 = build_bm25_text(s0[TITLE_COL], s0[TEXT_COL], s0[CAT_COL])
    vec0 = embed_texts([bm25_text0])[0]
    dim = len(vec0)

    print(f"[INFO] embed_model={EMBED_MODEL} dim={dim}")
    print(f"[INFO] qdrant={QDRANT_URL} collection={QDRANT_COLLECTION}")
    print(f"[INFO] elastic={ELASTIC_URL} index={ELASTIC_INDEX}")
    print(f"[INFO] catalog_rows={len(catalog_rows)} batch={BATCH} bulk_chunk={BULK_CHUNK}")
    print(f"[INFO] fairness TEXT_TEMPLATE='{TEXT_TEMPLATE}'")

    # Ensure storages
    ensure_qdrant_collection(dim)
    ensure_elastic_index()

    # Index in chunks: build docs once, then
    # - elastic bulk in BULK_CHUNK
    # - qdrant upsert in BATCH (embedding batch)
    # We keep both progress visible.
    total = len(catalog_rows)
    elastic_buf: List[Dict[str, Any]] = []
    sent_elastic = 0
    sent_qdrant = 0
    skipped = 0

    # For Qdrant, we embed in BATCH sized chunks
    for i in range(0, total, BATCH):
        chunk = catalog_rows[i:i+BATCH]

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

            # Elastic doc (same bm25_text)
            elastic_buf.append({
                "doc_id": doc_id,
                "title": title,
                "text": text,
                "category": cat,
                "bm25_text": bm25_text,
            })

            # Qdrant embedding input (same bm25_text)
            ids.append(doc_id)
            embed_inputs.append(bm25_text)
            q_payloads.append({
                "doc_id": doc_id,
                "title": title,
                "text": text,
                "category": cat,
                "bm25_text": bm25_text,
            })

        # Flush elastic in larger chunks
        while len(elastic_buf) >= BULK_CHUNK:
            batch_docs = elastic_buf[:BULK_CHUNK]
            elastic_buf = elastic_buf[BULK_CHUNK:]
            elastic_bulk(batch_docs)
            sent_elastic += len(batch_docs)
            print(f"[ELASTIC] {sent_elastic}/{total} (buffer={len(elastic_buf)})")

        # Qdrant upsert for this embed batch
        if ids:
            vecs = embed_texts(embed_inputs)
            points = [{"id": did, "vector": v, "payload": pl} for did, v, pl in zip(ids, vecs, q_payloads)]
            qdrant_upsert(points)
            sent_qdrant += len(points)

        if (i + BATCH) >= total or sent_qdrant % (BATCH * 5) == 0:
            print(f"[QDRANT] {sent_qdrant}/{total} (skipped={skipped})")

    # Flush remaining elastic
    if elastic_buf:
        elastic_bulk(elastic_buf)
        sent_elastic += len(elastic_buf)
        print(f"[ELASTIC] {sent_elastic}/{total} (final flush)")

    print("[DONE] Hybrid indexing completed")
    print(f"[SUMMARY] qdrant_sent={sent_qdrant}, elastic_sent={sent_elastic}, skipped={skipped}")
    print("Next:")
    print(" - BM25-only   : --vendor-set exp_hybrid_qdrant_elastic --pipeline bm25_only")
    print(" - Dense-only  : --vendor-set exp_hybrid_qdrant_elastic --pipeline dense_only")
    print(" - Hybrid RRF  : --vendor-set exp_hybrid_qdrant_elastic --pipeline hybrid_rrf")

if __name__ == "__main__":
    main()
