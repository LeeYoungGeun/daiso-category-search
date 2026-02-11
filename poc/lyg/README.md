# Intent Vector/Hybrid Lab (ivhl)

### 1) 환경변수 설정

프로젝트 루트에 `.env` 파일을 만들고 다음 중 필요한 키를 넣습니다.

- `OPENAI_API_KEY`
- `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY`

(`templates/.env.example` 참고)

---------------------------------------------------------------------------------------------------------------

### 테스트 실행방법
[BM25 only]

# BM25-only 실행 
```bash
python scripts\run_benchmark.py ^
  --vendors templates\vendors.example.yaml ^
  --pipelines templates\pipeline.example.yaml ^
  --vendor-set bm25_local ^
  --pipeline bm25_only ^
  --catalog data\catalog.30cat.v3.tsv ^
  --testcases templates\testcases.v6.tsv ^
  --out runs
```

# 노이즈
```bash
python scripts\run_benchmark.py ^
  --vendors templates\vendors.example.yaml ^
  --pipelines templates\pipeline.example.yaml ^
  --vendor-set bm25_local ^
  --pipeline bm25_only ^
  --catalog data\catalog.30cat.v3.tsv ^
  --testcases templates\testcases.v6.noisy.tsv ^
  --out runs
```

# 인덱싱
```bash
set OPENAI_API_KEY=sk-xxx
set QDRANT_URL=http://localhost:6333
set ELASTIC_URL=http://localhost:9200

python scripts\index_external_hybrid.py
```

# bm25 + dense + hybrid 실행 방법
```bash
ivhl run --vendor-set ext_qdrant_elastic --pipeline-id bm25_only  --catalog data\catalog.30cat.v3.tsv --testcases templates\testcases.v7.noisy.tsv --out-dir runs
ivhl run --vendor-set ext_qdrant_elastic --pipeline-id dense_only --catalog data\catalog.30cat.v3.tsv --testcases templates\testcases.v7.noisy.tsv --out-dir runs
ivhl run --vendor-set ext_qdrant_elastic --pipeline-id hybrid_rrf --catalog data\catalog.30cat.v3.tsv --testcases templates\testcases.v7.noisy.tsv --out-dir runs
```