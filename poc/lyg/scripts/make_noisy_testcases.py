import csv
import re
from pathlib import Path

def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def remove_traps(query: str, trap_keywords: str) -> str:
    q = query or ""
    traps = [t.strip() for t in (trap_keywords or "").split(",") if t.strip()]
    for t in sorted(traps, key=lambda x: (-len(x.split()), -len(x))):
        if " " in t:
            q = q.replace(t, " ")
    tokens = q.split()
    trap_set = set([t for t in traps if " " not in t])
    tokens = [tok for tok in tokens if tok not in trap_set]
    return normalize_spaces(" ".join(tokens))

def add_traps(query: str, trap_keywords: str) -> str:
    q = normalize_spaces(query or "")
    traps = [t.strip() for t in (trap_keywords or "").split(",") if t.strip()]
    existing_tokens = set(q.split())
    additions = []
    for t in traps:
        if " " in t:
            if t not in q:
                additions.append(t)
        else:
            if t not in existing_tokens:
                additions.append(t)
    if additions:
        q = normalize_spaces(q + " " + " ".join(additions))
    return q

def main(src_tsv: Path, clean_out: Path, noisy_out: Path):
    rows = []
    with src_tsv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            rows.append(r)

    # 1) clean: bm25_query_text에서 trap_keywords 제거
    clean_rows = []
    for r in rows:
        rr = dict(r)
        rr["bm25_query_text"] = remove_traps(rr.get("bm25_query_text",""), rr.get("trap_keywords",""))
        clean_rows.append(rr)

    # 2) noisy: clean bm25_query_text에 trap_keywords 추가
    noisy_rows = []
    for r_clean, r_src in zip(clean_rows, rows):
        rr = dict(r_clean)
        rr["bm25_query_text"] = add_traps(rr.get("bm25_query_text",""), r_src.get("trap_keywords",""))
        noisy_rows.append(rr)

    fieldnames = list(rows[0].keys()) if rows else []
    for p, rws in [(clean_out, clean_rows), (noisy_out, noisy_rows)]:
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            w.writeheader()
            w.writerows(rws)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="source TSV (has trap_keywords column)")
    ap.add_argument("--clean-out", default="testcases.clean.tsv")
    ap.add_argument("--noisy-out", default="testcases.noisy.tsv")
    args = ap.parse_args()
    main(Path(args.src), Path(args.clean_out), Path(args.noisy_out))
