import os, csv, time, json, re, uuid
from typing import Dict, List, Any, Tuple, Optional

import requests
from openai import OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
QDRANT_URL = os.environ.get("QDRANT_URL", "").strip().rstrip("/")
ELASTIC_URL = os.environ.get("ELASTIC_URL", "").strip().rstrip("/")
if not OPENAI_API_KEY:
    raise SystemExit("Missing OPENAI_API_KEY")
if not QDRANT_URL:
    raise SystemExit("Missing QDRANT_URL")
if not ELASTIC_URL:
    raise SystemExit("Missing ELASTIC_URL")

QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "").strip()
ELASTIC_API_KEY = os.environ.get("ELASTIC_API_KEY", "").strip()
ELASTIC_AUTH_HEADER = os.environ.get("ELASTIC_AUTH_HEADER", "").strip()

QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "products").strip()
ELASTIC_INDEX = os.environ.get("ELASTIC_INDEX", "products").strip()

EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small").strip()

CATALOG_TSV = os.environ.get("CATALOG_TSV", "data/catalog.30cat.v3.tsv")
BATCH = int(os.environ.get("BATCH", "128"))
BULK_CHUNK = int(os.environ.get("BULK_CHUNK", "500"))

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
MAX_RETRY = int(os.environ.get("MAX_RETRY", "5"))
RETRY_SLEEP_BASE = float(os.environ.get("RETRY_SLEEP_BASE", "1.5"))

ID_COL, TITLE_COL, TEXT_COL, CAT_COL = "doc_id", "title", "text", "category"

# ✅ doc_id -> UUID (stable)
UUID_NAMESPACE = uuid.UUID(os.environ.get("QDRANT_UUID_NAMESPACE", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"))
# default: uuid.NAMESPACE_DNS (stable, widely used)

client = OpenAI(api_key=OPENAI_API_KEY)

def read_tsv(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        rows = list(r)
        return rows, r.fieldnames or []

def http_retry(method: str, url: str, *, headers: Dict[str, str], json_body: Any = None, data: Any = None) -> requests.Response:
    last_exc = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = requests.request(method, url, headers=headers, json=json_body, data=data, timeout=HTTP_TIMEOUT)
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(RETRY_SLEEP_BASE * attempt)
                continue
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(RETRY_SLEEP_BASE * attempt)
    raise RuntimeError(f"HTTP failed after retries: {url}, last={last_exc}")

def qdrant_headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if QDRANT_API_KEY:
        h["api-key"] = QDRANT_API_KEY
    return h

def ensure_qdrant_collection(dim: int):
    r = http_retry("GET", f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", headers=qdrant_headers())
    if r.status_code == 200:
        return
    body = {"vectors": {"size": dim, "distance": "Cosine"}}
    cr = http_retry("PUT", f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", headers=qdrant_headers(), json_body=body)
    if cr.status_code not in (200, 201):
        raise RuntimeError(f"Create Qdrant collection failed: {cr.status_code} {cr.text}")

def qdrant_upsert(points: List[Dict[str, Any]]):
    body = {"points": points}
    r = http_retry("PUT", f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points?wait=true", headers=qdrant_headers(), json_body=body)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Qdrant upsert failed: {r.status_code} {r.text}")

def elastic_headers_json() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if ELASTIC_AUTH_HEADER:
        h["Authorization"] = ELASTIC_AUTH_HEADER
        return h
    if ELASTIC_API_KEY:
        key = ELASTIC_API_KEY.strip()
        if key.lower().startswith(("apikey ", "bearer ", "basic ")):
            h["Authorization"] = key
        else:
            h["Authorization"] = f"ApiKey {key}"
    return h

def elastic_headers_ndjson() -> Dict[str, str]:
    h = {"Content-Type": "application/x-ndjson"}
    if "Authorization" in elastic_headers_json():
        h["Authorization"] = elastic_headers_json()["Authorization"]
    return h

def ensure_elastic_index():
    r = http_retry("HEAD", f"{ELASTIC_URL}/{ELASTIC_INDEX}", headers=elastic_headers_json())
    if r.status_code == 200:
        return
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
    cr = http_retry("PUT", f"{ELASTIC_URL}/{ELASTIC_INDEX}", headers=elastic_headers_json(), json_body=body)
    if cr.status_code not in (200, 201):
        raise RuntimeError(f"Create Elastic index failed: {cr.status_code} {cr.text}")

def elastic_bulk(docs: List[Dict[str, Any]]):
    lines = []
    for d in docs:
        _id = d["doc_id"]  # ✅ Elastic은 원래 doc_id 사용
        lines.append(json.dumps({"index": {"_index": ELASTIC_INDEX, "_id": _id}}, ensure_ascii=False))
        lines.append(json.dumps(d, ensure_ascii=False))
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    r = http_retry("POST", f"{ELASTIC_URL}/_bulk?refresh=true", headers=elastic_headers_ndjson(), data=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Elastic bulk failed: {r.status_code} {r.text}")
    out = r.json()
    if out.get("errors"):
        raise RuntimeError(f"Elastic bulk errors: {out}")

def embed_texts(texts: List[str]) -> List[List[float]]:
    last_exc = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as e:
            last_exc = e
            time.sleep(RETRY_SLEEP_BASE * attempt)
    raise RuntimeError(f"Embedding failed: {last_exc}")

def bm25_text(title: str, text: str) -> str:
    s = f"{(title or '').strip()} {(text or '').strip()}".strip()
    s = re.sub(r"\s+", " ", s)
    return s

def docid_to_uuid(doc_id: str) -> str:
    # ✅ stable uuid for each doc_id
    return str(uuid.uuid5(UUID_NAMESPACE, doc_id))

def main():
    rows, headers = read_tsv(CATALOG_TSV)
    for col in (ID_COL, TITLE_COL, TEXT_COL, CAT_COL):
        if col not in headers:
            raise SystemExit(f"Catalog missing {col}. headers={headers}")

    probe = bm25_text(rows[0][TITLE_COL], rows[0][TEXT_COL])
    dim = len(embed_texts([probe])[0])
    print(f"[INFO] embed_model={EMBED_MODEL} dim={dim}")

    ensure_qdrant_collection(dim)
    ensure_elastic_index()

    elastic_buf: List[Dict[str, Any]] = []
    sent_q, sent_e, skipped = 0, 0, 0

    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i+BATCH]
        ids, inputs, payloads = [], [], []

        for r in chunk:
            doc_id = (r.get(ID_COL) or "").strip()
            title = (r.get(TITLE_COL) or "").strip()
            text = (r.get(TEXT_COL) or "").strip()
            cat = (r.get(CAT_COL) or "").strip()
            if not doc_id or not text:
                skipped += 1
                continue

            t = bm25_text(title, text)

            # Elastic doc
            elastic_buf.append({
                "doc_id": doc_id,
                "title": title,
                "text": text,
                "category": cat,
                "bm25_text": t,
            })

            # Qdrant: use UUID id, store original doc_id in payload
            qid = docid_to_uuid(doc_id)

            ids.append(qid)
            inputs.append(t)
            payloads.append({
                "doc_id": doc_id,     # ✅ original
                "title": title,
                "text": text,
                "category": cat,
                "bm25_text": t,
            })

        while len(elastic_buf) >= BULK_CHUNK:
            batch_docs = elastic_buf[:BULK_CHUNK]
            elastic_buf = elastic_buf[BULK_CHUNK:]
            elastic_bulk(batch_docs)
            sent_e += len(batch_docs)
            print(f"[ELASTIC] {sent_e}/{len(rows)}")

        if ids:
            vecs = embed_texts(inputs)
            points = [{"id": qid, "vector": v, "payload": pl} for qid, v, pl in zip(ids, vecs, payloads)]
            qdrant_upsert(points)
            sent_q += len(points)
            print(f"[QDRANT] {sent_q}/{len(rows)}")

    if elastic_buf:
        elastic_bulk(elastic_buf)
        sent_e += len(elastic_buf)
        print(f"[ELASTIC] {sent_e}/{len(rows)} (final)")

    print("[DONE]", {"qdrant_sent": sent_q, "elastic_sent": sent_e, "skipped": skipped})

if __name__ == "__main__":
    main()
