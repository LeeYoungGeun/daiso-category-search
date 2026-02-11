# Changelog

All notable changes to this project will be documented in this file.

## [2.1.1] - 2026-02-11

### Added (ML Rerank — simulated/local modes, vendor sampling)

- **`simulated` mode** (`RERANK_MODE=simulated`, now default):
  - No external AI API calls — env-driven latency/error simulation
  - `SIM_TARGET_LATENCY_MS` (default 300), `SIM_JITTER_MS` (default 150)
  - `SIM_TIMEOUT_RATE` (0.01), `SIM_RATE_LIMIT_RATE` (0.02), `SIM_VENDOR_ERROR_RATE` (0.005)
  - On simulated error: `is_fallback=true` + local keyword fallback

- **`local` mode** (`RERANK_MODE=local`):
  - Deterministic token-overlap scoring (query vs name/desc/category)
  - Same input always produces same output (no randomness)
  - Confidence normalised to [0.0, 1.0]

- **`VENDOR_SAMPLE_RATE`** env var (0.0–1.0, default 1.0):
  - Controls how often `vendor` mode actually calls the Gemini LLM
  - `VENDOR_SAMPLE_RATE=0` blocks all vendor calls (local fallback)

- **Standardised `error_type`**: `RATE_LIMIT` | `TIMEOUT` | `VENDOR_ERROR` | `None`

### Changed

- Default `RERANK_MODE` changed from `mock` → `simulated`
- Vendor error fallback now returns `error_type="VENDOR_ERROR"` (was raw exception string)

### Tests

- 25 new tests (`tests/test_ml_rerank_v2.py`): simulated (10), local (8), vendor sampling (3), default mode (2), error_type standard (2)
- Full regression: **70 passed** (27 existing + 18 v2.1.0 + 25 new)

## [2.1.0] - 2026-02-10

### Added (ML Rerank Layer — QPM Load-Testing)

- **ML Rerank Service** (`backend/ml/rerank_service.py`):
  - `RerankService` class with `RERANK_MODE=mock|vendor` switch (env var)
  - `mock` mode: deterministic first-candidate selection, <1ms latency, no LLM
  - `vendor` mode: delegates to existing `backend.logic.reranker.rerank_candidates` (Gemini LLM)
  - Standardised response: `selected_id`, `reason`, `confidence`, `latency_ms`, `is_fallback`, `error_type`
  - Graceful fallback on vendor errors with `is_fallback=True` and `error_type` populated

- **`POST /ml/rerank` Endpoint** (`backend/dev_server.py`):
  - HTTP endpoint exposing M2 reranker for QPM load-testing
  - `X-Rerank-Latency-Ms` response header for external monitoring
  - Request validation via Pydantic (`RerankRequest` model)

- **Load Test Scripts**:
  - `scripts/loadtest_rerank.js`: k6 script with smoke/load/spike scenarios, custom `rerank_latency_ms` metric, QPM summary
  - `scripts/loadtest_rerank.py`: Python asyncio+httpx load tester (no external deps), p50/p95/p99 reporting

- **Tests** (`tests/test_ml_rerank.py`):
  - 18 tests: mock mode (5), vendor mode (2), edge cases (5), HTTP endpoint (6)
  - TDD: Red→Green cycle verified (12 FAILED + 6 ERROR → 18 passed)
  - Full regression: 45 tests passed (27 existing + 18 new)

## [2.0.0] - 2026-02-10

### Added (M2: Reranking / Ambiguity Handling Enhancement)

- **Ambiguity Detection Module** (`backend/logic/ambiguity.py`):
  - `AmbiguityType` enum: `NONE`, `BROAD_CATEGORY`, `VAGUE_DESCRIPTION`, `MULTI_INTENT`, `NO_RESULTS`
  - `detect_ambiguity()`: Rule-based ambiguity classifier using item, attrs, candidate count, category spread
  - `calculate_category_spread()`: Counts distinct categories across search results
  - `generate_clarification_options()`: Builds drill-down options from category groupings
  - `build_clarification_question()`: Generates polite Korean follow-up questions with numbered options
  - `should_fallback()`: 2-strike fallback gate (stops asking after 2 clarification attempts)

- **Enhanced Reranker Module** (`backend/logic/reranker.py`):
  - `rerank_candidates()`: LLM-based reranking with confidence scoring (0.0–1.0)
  - Gemini 2.0 Flash integration with CoT reasoning prompt
  - Fallback keyword-matching reranker when LLM unavailable
  - Null-safe: returns `selected_id=null` when no candidate matches

- **Schema Enhancements** (`backend/logic/schemas.py`):
  - `AmbiguityType` enum added
  - `NLUResponse.ambiguity_type` field (default: `NONE`)
  - `NLUResponse.confidence` field (default: `1.0`)

- **Pipeline Integration** (`backend/logic/integrated_search.py`):
  - Step 4: Ambiguity detection after search (category spread analysis)
  - Step 4b: Clarification question generation or 2-strike fallback
  - Step 5: Enhanced reranking with confidence scoring
  - New response fields: `needs_clarification`, `clarification_question`, `clarification_options`, `clarification_count`, `is_fallback`

- **API Enhancements** (`backend/main.py`):
  - `SearchRequest.clarification_count`: Track clarification attempts across turns
  - `SearchResponse.needs_clarification`: Whether client should show follow-up question
  - `SearchResponse.clarification_question`: The follow-up question text (Korean)
  - `SearchResponse.clarification_options`: Structured drill-down options
  - `SearchResponse.clarification_count`: Updated count for next request
  - `SearchResponse.is_fallback`: Whether results are best-effort after 2 strikes

- **Agent Graph Update** (`backend/logic/agent_graph.py`):
  - New `rerank` node between ambiguity check and response
  - M2 ambiguity detection replaces simple heuristic
  - 2-strike fallback integrated into graph flow
  - Reranking reorders candidates before final response

- **Tests** (`tests/test_m2_ambiguity.py`):
  - 27 test cases covering all M2 features
  - `TestSchemas`: AmbiguityType enum, NLUResponse fields, defaults
  - `TestAmbiguityDetection`: Broad category, vague description, no results, clear query, multi-intent, category spread
  - `TestFollowUpQuestions`: Option generation, question formatting
  - `TestTwoStrikeFallback`: Strike counting, fallback trigger
  - `TestReranking`: Basic rerank, confidence scoring, null handling, empty candidates
  - `TestIntegratedPipeline`: End-to-end pipeline with clarification and fallback
  - `TestAPIEndpoints`: Request/Response model contracts

### M2 Feature Summary

| Feature | Description | Status |
|---------|-------------|--------|
| Ambiguity Detection | 5-type classifier (NONE/BROAD/VAGUE/MULTI/NO_RESULTS) | ✅ |
| Follow-up Questions | Category-based drill-down with Korean options | ✅ |
| 2-Strike Fallback | Stop asking after 2 attempts, show best-effort | ✅ |
| Enhanced Reranking | LLM reranking with confidence + keyword fallback | ✅ |
| API Clarification Flow | Request/Response models for multi-turn clarification | ✅ |

---

## [1.0.0] - 2026-02-10

### Added (M1: Hybrid Search Infrastructure)
- **Docker Compose**: Elasticsearch 8.13.4 + Qdrant v1.9.7 + Redis 7.2 (`docker-compose.yml`)
- **Hybrid Search Service** (`backend/search/`):
  - `config.py`: Environment-based configuration for all external services
  - `embedding.py`: Google Gemini embedding adapter (gemini-embedding-001, 3072-dim)
  - `hybrid.py`: BM25 (Elasticsearch) + Vector (Qdrant) + RRF/Weighted Fusion
  - `indexer.py`: Catalog TSV → Elasticsearch + Qdrant indexer (CLI)
  - `benchmark.py`: Automated hit@k / MRR / NDCG benchmark runner (CLI)
- **Test Script**: `scripts/m1_test.py` — End-to-end test (health → index → search → benchmark)
- **Pipeline Integration**: `backend/logic/integrated_search.py` now uses hybrid search with SQLite fallback

### Benchmark Results (88 test cases, 459 products)
| Mode | hit@1 | hit@3 | hit@5 | hit@10 | MRR | NDCG@10 | Avg Latency |
|------|-------|-------|-------|--------|-----|---------|-------------|
| **Hybrid (RRF)** | 84.1% | 97.7% | **98.9%** | 100% | 90.8% | 92.8% | 375ms |
| BM25 Only | 79.5% | 92.0% | 97.7% | 100% | 86.6% | 89.6% | 24ms |
| Dense Only | 89.8% | 95.5% | 100% | 100% | 93.3% | 93.7% | 352ms |

### Changed
- `.env` / `.env.example`: Added Qdrant, Elasticsearch, Redis, embedding, and search parameters
- `backend/logic/integrated_search.py`: Hybrid search with automatic SQLite fallback

## [0.6.0] - 2026-02-05

### Synced (Search-Roca v0.8.1)
- **PoC Integration**: Synced latest `search-roca` PoC v5 & v6 files to `poc/bjy/`.
  - **Modules**: `backend`, `frontend`, `poc` (Reasoning Engine, Map Debugger, Latency Benchmark).
  - **Data**: Updated Mock Product DB and Map Data.
- **Dependencies**: Updated `requirements.txt` to match `search-roca` environment.
- **Maintenance**: Moved old PoC files to `poc/bjy/old/` and gitignored them.

## [0.5.0] - 2026-02-05

### Added (PoC v2 Integration)
- **Integration**: Ported complete PoC v2 AG Module from `search-roca`.
- **Scripts** (`poc/`):
    - `poc_v2_step1_query_processor.py`: Intent Extraction.
    - `poc_v2_step2_hybrid_retrieval.py`: Hybrid Search (BM25+Vector).
    - `poc_v2_step3_ag_reranker.py`: LLM Reranking & Location Guide.
    - `poc_v2_generate_mock_data.py`: Mock DB enrichment w/ LLM.
    - `poc_v2_generate_golden_dataset.py`: 30 Hard Test Cases.
- **Reports**:
    - `poc/POC_v2_FINAL_REPORT.md`: Overall PoC summary validation report.

## [0.3.1] - 2026-01-19

### Added (RAG Robustness PoC)
- **Integration**: Merged RAG Optimization PoC from `search-roca` into main repo.
- **Scripts** (`poc/`):
    - `RAG_System_experiment_keyword.py`: Verified K=30/Keyword Optimization script.
    - `RAG_System_experiment_baseline.py`: Sentence-input baseline script.
    - `generate_large_data.py`: 200-product scaling data generator.
- **Reports** (`docs/`):
    - `RAG_ROBUSTNESS.md`: Final optimization report (K=30 Success).
    - `RAG_BASELINE.md`: Baseline failure analysis.
- **Prompts**: `poc/prompts/intent_rules_prompt.txt` (Rule-based Intent Classification).

---

## [0.3.0] - 2026-01-16

### Added (LangGraph Migration)
- **Logic**: Migrated backend logic to `LangGraph` (Cyclic State Machine)
- **Agent**: Implemented 5-node workflow (`NLU`, `Search`, `AmbiguityCheck`, `Clarification`, `Response`)
- **Context**: Full conversation history persistence using `MemorySaver`
- **Frontend**: Added `/kioskmode` route and Landing Page UI
- **Dependencies**: `langgraph`, `langchain`, `langchain-google-genai`

### Improved
- **Clarification**: Added "Drill-Down" logic to clarify broad categories (e.g., Cleaning -> Detergent vs Tools)
- **Loop Prevention**: Fixed infinite loop bug where AI kept asking same questions
- **Language**: Strictly enforced Korean output in system prompts

## [0.2.0] - 2026-01-16

### Added
- **Category System**: Product categorization with major/middle categories (대분류/중분류)
- `category_matcher.py`: Keyword-based category matching script
- `categories` table: 48 category entries (12 major × multiple middle)
- Products table now has `category_major` and `category_middle` columns

### Stats
- 401 products matched (67%)
- 200 products unmatched (to be fixed with full re-crawl)

## [0.1.1] - 2026-01-16

### Fixed
- Updated `requirements.txt` with exact package versions from search-roca conda environment
- Added missing dependencies: `sentence-transformers`, `huggingface-hub`, `tokenizers`, `safetensors`, `scipy`, `scikit-learn`

## [0.1.0] - 2026-01-16

### Added
- **Product Database** (`backend/database/`)
  - `products.db`: SQLite database with 601 crawled products
  - `images/`: 601 product images from Daiso Mall ranking
  - `database.py`: Database operations module
  - `embeddings.py`: CLIP-based multimodal embeddings (text + image)
  - `generate_test_data.py`: 3000 test utterances generator (85% normal, 15% hard)

### Database Schema
- `products`: id, rank, name, price, image_url, image_name, image_path
- `test_utterances`: utterance, difficulty, expected_product_id
- `product_embeddings`: text_embedding, image_embedding (CLIP 512-dim vectors)

### Dependencies Added
- `selenium`, `webdriver-manager`: Web crawling
- `transformers`, `torch`: CLIP embeddings
- `Pillow`: Image processing

---

## [0.0.0] - Initial

- Initial project setup
- Basic FastAPI backend structure
- Frontend placeholder
