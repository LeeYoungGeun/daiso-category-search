# Daiso Category Search — AI 기반 매장 검색 시스템

음성/텍스트 입력 → STT 변환 → NLU 의도 분석 → 의도 추출·키워드 확장(Gemini) → 하이브리드 검색(BM25+Vector+RRF) → 모호성 판별 → ML 리랭킹 → 매장 위치 안내

---

## 목차

1. [프로젝트 구조](#1-프로젝트-구조)
2. [핵심기능 프로세스 및 기능 통합](#2-핵심기능-프로세스-및-기능-통합)
3. [필수 프로그램 설치](#3-필수-프로그램-설치)
4. [환경변수 설정](#4-환경변수-설정)
5. [로컬 배포 진행 순서](#5-로컬-배포-진행-순서)
6. [기능별 테스트 방법 (poc, tests, scripts)](#6-기능별-테스트-방법)
7. [벤치마크 테스트 (검색 품질 평가)](#7-벤치마크-테스트-검색-품질-평가)
8. [통합 테스트 — Vendor OFF](#8-통합-테스트--vendor-off)
9. [통합 테스트 — Vendor ON](#9-통합-테스트--vendor-on)
10. [서버 A 배포 가이드 (App)](#10-서버-a-배포-가이드-app--3396105)
11. [서버 B 배포 가이드 (Search/Data)](#11-서버-b-배포-가이드-searchdata--541801204)
12. [배포 후 인프라 설정·실행·설치 순서](#12-배포-후-인프라-설정실행설치-순서)
13. [운영 필수 모듈 실행방법](#13-운영-필수-모듈-실행방법)
14. [기타 모듈 설치 및 실행](#14-기타-모듈-설치-및-실행)

---

## 1. 프로젝트 구조

```
daiso-category-search/
├── backend/
│   ├── main.py                  # FastAPI 서버 (운영 진입점)
│   ├── config.yaml              # STT/검색/정책 설정
│   ├── ws_stt.py                # WebSocket STT 핸들러
│   ├── logic/
│   │   ├── integrated_search.py # 전체 파이프라인 (7단계 통합)
│   │   ├── nlu.py               # Gemini NLU (backend 버전)
│   │   ├── reranker.py          # Gemini LLM 리랭킹
│   │   ├── agent_graph.py       # LangGraph 에이전트
│   │   ├── ambiguity.py         # 모호성/다의어/꼬리질문
│   │   ├── prompts.py           # 프롬프트 템플릿
│   │   └── schemas.py           # 데이터 스키마
│   ├── search/
│   │   ├── hybrid.py            # BM25 + Vector + RRF Fusion
│   │   ├── indexer.py           # DB → ES/Qdrant 색인
│   │   ├── embedding.py         # Gemini 임베딩
│   │   ├── cache.py             # ★ Redis 캐시 (키워드확장+검색결과)
│   │   ├── benchmark.py         # 검색 품질 벤치마크 (Hit@K, MRR, NDCG)
│   │   └── config.py            # 환경변수 기반 설정 (ES/Qdrant/Redis)
│   ├── database/
│   │   ├── products.db          # 상품 데이터 (SQLite)
│   │   ├── database.py          # DB CRUD
│   │   ├── crawler.py           # 상품 크롤러
│   │   ├── category_matcher.py  # 카테고리 대/중분류 매핑
│   │   └── embeddings.py        # CLIP 임베딩
│   └── ml/
│       └── rerank_service.py    # ML 리랭킹 (mock/vendor/simulated/local)
│
├── poc/                         # PoC 실험 (팀별)
│   ├── kms/nlu.py               # ★ 운영 NLU (Gemini 2.0 Flash)
│   ├── kdg/                     # 리랭킹 실험
│   ├── lyg/                     # 하이브리드 검색 실험 + 벤치마크 테스트셋
│   │   ├── data/catalog.30cat.v3.tsv        # 30개 카테고리 카탈로그
│   │   ├── templates/testcases.v7.tsv       # 벤치마크 테스트셋
│   │   ├── templates/testcases.v7.clean.tsv # 클린 테스트셋
│   │   ├── templates/testcases.v7.noisy.tsv # 노이즈 테스트셋
│   │   └── scripts/run_benchmark.py         # 벤치마크 실행 스크립트
│   ├── stt/                     # STT 어댑터 (Whisper/Google)
│   ├── bjy/, lsy/, intent/      # 기타 실험
│
├── frontend/                    # Next.js 프론트엔드
│   ├── Dockerfile
│   └── src/lib/api.ts           # API 클라이언트 (REST + WS)
│
├── infra/
│   ├── docker-compose.app.yml   # 서버 A (API+FE)
│   ├── docker-compose.data.yml  # 서버 B (ES+Qdrant+Redis)
│   ├── nginx-host.conf          # Nginx 호스트 설정
│   ├── start_data.sh            # 서버 B 시작 스크립트
│   └── monitor.sh               # 메모리 모니터링
│
├── scripts/                     # 부하 테스트
├── tests/                       # pytest 테스트
├── docker-compose.yml           # 로컬 개발 인프라
├── Dockerfile                   # Backend Docker 이미지
├── requirements.txt             # Python 의존성 (3.12)
├── .env.example                 # 환경변수 템플릿
├── start_server.bat             # 로컬 시작 스크립트
└── start_server_live.bat        # 라이브 시작 스크립트
```

---

## 2. 핵심기능 프로세스 및 기능 통합

### 2-1. 전체 파이프라인 (7단계)

```
사용자 입력 (음성/텍스트)
    │
    ▼
┌──────────────────────────────────┐
│  Step 1. STT 변환                │  Whisper(로컬) / Google Cloud STT
│  음성 → 텍스트                   │  WebSocket 실시간 스트리밍 지원
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  Step 2. NLU 의도 분석           │  Gemini 2.0 Flash
│  ├─ intent 분류                  │  PRODUCT_SEARCH / UNSUPPORTED / OTHER
│  ├─ slots 추출                   │  item, attrs, query_rewrite
│  └─ needs_clarification 판별    │  모호 여부 사전 감지
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  Step 3. 의도 추출 · 키워드 확장  │  Gemini (expand_search_keywords)
│  ├─ primary_keyword 추출         │  NLU slots.item 또는 query_rewrite
│  ├─ 유의어/관련어 확장 (Top 3)    │  "볼펜" → ["볼펜","필기구","펜"]
│  └─ 중복 제거 후 검색 키워드 확정 │
│                                   │
│  ★ Redis 캐시 적용 (TTL 5분)     │  동일 키워드 → Gemini 호출 생략
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────────────────┐
│  Step 4. 하이브리드 검색                      │
│  ├─ BM25 검색 (Elasticsearch)                │  키워드 매칭 (top_k=30)
│  ├─ Vector 검색 (Qdrant + Gemini Embedding)  │  의미 유사도 (top_k=30)
│  └─ RRF Fusion                               │  두 결과 점수 통합 (top_k=10)
│                                               │
│  ★ Redis 캐시 적용 (TTL 5분)                 │  동일 키워드셋 → ES/Qdrant 호출 생략
│  ※ Fallback: SQLite LIKE 검색               │  ES/Qdrant 장애 시 자동 전환
└──────────┬───────────────────────────────────┘
           ▼
┌──────────────────────────────────┐
│  Step 5. 모호성 판별 (M2)        │
│  ├─ 카테고리 분산도 계산          │  결과가 여러 카테고리에 걸칠 때
│  ├─ 모호 → 꼬리질문 생성         │  "청소용품" → "세제? 청소솔?"
│  └─ 2-strike fallback           │  2회 질문 후 → 최선 결과 반환
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  Step 6. ML 리랭킹               │  RERANK_MODE 에 따라 분기
│  ├─ live: Gemini LLM 리랭킹     │  의도 기반 최적 상품 선택
│  ├─ vendor: 외부 벤더 API 호출   │  유료 API (Cohere 등)
│  ├─ simulated: mock + jitter    │  벤더 시뮬레이션 (디버깅용)
│  ├─ local: 키워드 매칭 fallback  │  오프라인 환경용
│  └─ mock: 첫 번째 후보 반환      │  테스트용
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  Step 7. 위치 안내 + QR 핸드오버  │
│  ├─ 카테고리 매칭                │  대분류 > 중분류 자동 매핑
│  ├─ 매장 위치 텍스트 생성        │
│  └─ QR 코드 페이로드 (top1)      │  모바일 핸드오버용
└──────────────────────────────────┘
```

### 2-2. 기능 통합 구조

| 계층 | 역할 | 모듈 |
|---|---|---|
| **API Layer** | REST + WebSocket 엔드포인트 | `backend/main.py` |
| **Pipeline** | 7단계 통합 오케스트레이션 | `backend/logic/integrated_search.py` |
| **NLU** | 의도 분석 + 키워드 추론 | `poc/kms/nlu.py` (Gemini 2.0 Flash) |
| **NLU (legacy)** | 의도 분석 (이전 버전) | `backend/logic/nlu.py` (Gemini 1.5 Flash) |
| **키워드 확장** | 유의어/관련어 확장 | `poc/kms/nlu.py` → `expand_search_keywords()` |
| **하이브리드 검색** | BM25 + Vector + RRF Fusion | `backend/search/hybrid.py` |
| **인덱서** | DB → ES/Qdrant 색인 | `backend/search/indexer.py` |
| **임베딩** | Gemini Embedding | `backend/search/embedding.py` |
| **모호성 판별** | 다의어/포괄어 + 꼬리질문 | `backend/logic/ambiguity.py` |
| **리랭킹** | Gemini LLM 기반 리랭킹 | `backend/logic/reranker.py` |
| **ML Rerank** | 4-mode 리랭킹 서비스 | `backend/ml/rerank_service.py` |
| **에이전트** | LangGraph 순환 워크플로우 | `backend/logic/agent_graph.py` |
| **STT** | Whisper + Google Cloud STT | `poc/stt/` |
| **상품 DB** | 크롤링 + SQLite 관리 | `backend/database/` |
| **Redis 캐시** | 키워드 확장 + 검색 결과 캐시 (TTL 5분) | `backend/search/cache.py` |

### 2-3. API 엔드포인트

| Method | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 서버 상태 확인 (Redis 캐시 상태 포함) |
| POST | `/v1/search` | 통합 검색 (NLU→검색→리랭킹) |
| POST | `/v1/stt/process` | 음성 파일 → 검색 결과 |
| WS | `/ws/stt` | 실시간 음성 스트리밍 STT |
| POST | `/ml/rerank` | ML 리랭킹 단독 호출 |
| DELETE | `/cache` | Redis 캐시 전체 삭제 (운영 중 캐시 무효화) |

### 2-4. RERANK_MODE 정리

| 모드 | 리랭커 | 비용 | 용도 |
|---|---|---|---|
| `mock` | 첫 번째 후보 반환 | 무료 | 단위 테스트 |
| `simulated` | mock + 지연 시뮬레이션 | 무료 | 벤더 시뮬레이션 |
| `local` | 키워드 매칭 fallback | 무료 | 오프라인/격리 테스트 |
| **`live`** | **Gemini LLM 리랭킹** | Gemini 무료 | **운영 기본값** |
| `vendor` | 외부 벤더 API (Cohere 등) | **유료** | 품질 비교 테스트 |

### 2-5. 통합 검색 응답 구조

```json
{
  "request_id": "uuid",
  "query": "건전지 찾아줘",
  "intent": "PRODUCT_SEARCH",
  "is_in_scope": true,
  "needs_clarification": false,
  "top3": [
    {
      "product_id": "...",
      "name": "알카라인 건전지 AA",
      "price": 1000,
      "category_major": "생활용품",
      "category_middle": "건전지/충전지",
      "location_text": "생활용품 > 건전지/충전지",
      "is_top1": true
    }
  ],
  "timing_ms": {
    "nlu": 450,
    "expand": 280,
    "search": 120,
    "ambiguity": 5,
    "rerank": 350,
    "location": 2,
    "total": 1207
  },
  "metadata": {
    "search_mode": "hybrid",
    "keywords": { "primary": "건전지", "expanded": ["건전지","배터리","AA건전지"], "cache_hit": false },
    "search":   { "candidates_count": 10, "mode": "hybrid", "cache_hit": true }
  }
}
```

> **cache_hit** 필드: 동일 키워드 재검색 시 `true`로 변경되며, Gemini/ES/Qdrant 호출을 건너뜁니다.

### 2-6. Redis 캐시 동작

| 항목 | 설명 |
|---|---|
| **모듈** | `backend/search/cache.py` |
| **캐시 대상** | ① 키워드 확장 결과 (`daiso:expand:*`) ② 하이브리드 검색 결과 (`daiso:search:*`) |
| **TTL** | 5분 (300초), `REDIS_CACHE_TTL` 환경변수로 변경 가능 |
| **Graceful degradation** | Redis 미연결 시 캐시 비활성화 (에러 전파 없음, 검색은 정상 동작) |
| **캐시 무효화** | `DELETE /cache` API 또는 Redis TTL 만료 |
| **로그** | 서버 시작 시 Redis 연결 상태, 검색 시 HIT/MISS 로그 출력 |

**환경변수:**

| 변수명 | 기본값 | 설명 |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 접속 URL |
| `REDIS_CACHE_TTL` | `300` | 캐시 유효 시간 (초) |

---

## 3. 필수 프로그램 설치

### 3-1. 필수 프로그램

| 프로그램 | 버전 | 용도 |
|---|---|---|
| **Python** | **3.12** | Backend (FastAPI) |
| Node.js | 18+ | Frontend (Next.js) |
| Docker Desktop | 최신 | ES, Qdrant, Redis |
| Git | 최신 | 소스 관리 |
| Conda *(선택)* | 최신 | Python 환경 관리 |

### 3-2. Python 환경 설정

```bash
# Conda 사용 시
conda create -n proj11 python=3.12
conda activate proj11

# pip 설치
pip install -r requirements.txt
```

### 3-3. 프론트엔드 설치

```bash
cd frontend
npm install
```

---

## 4. 환경변수 설정

### 4-1. 환경변수 파일 구조

| 파일 | 용도 | Git 포함 | 설명 |
|---|---|---|---|
| `.env.example` | 템플릿 (API Key 없음) | ✅ | 새 환경 설정 시 복사 |
| `.env.local` | 로컬 개발 (localhost) | ❌ | Docker 내부 서비스 → localhost |
| `.env.live` | 라이브 (서버 B IP) | ❌ | 서비스 → 54.180.1.204 |
| `.env` | **실제 사용** (위 파일 중 하나 복사) | ❌ | 앱이 읽는 파일 |

### 4-2. 주요 환경변수

| 변수 | 로컬 | 라이브 | 설명 |
|---|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | `http://54.180.1.204:6333` | Qdrant 벡터 DB |
| `ELASTIC_URL` | `http://localhost:9200` | `http://54.180.1.204:9200` | Elasticsearch |
| `REDIS_URL` | `redis://localhost:6379/0` | `redis://54.180.1.204:6379/0` | Redis 캐시 |
| `RERANK_MODE` | `live` / `local` | `live` | 리랭킹 모드 (5종) |
| `VENDOR_ENABLED` | `false` | `true/false` | 벤더 API 사용 여부 |
| `VENDOR_SAMPLE_RATE` | `0` | `0~100` | 벤더 샘플링 비율 |
| `VENDOR_MAX_CALLS_PER_MIN` | `0` | `0~N` | 벤더 분당 최대 호출 |
| `CORS_ORIGIN` | - | `http://3.39.6.105` | 프론트엔드 도메인 |

> `RERANK_MODE`는 5가지 모드 지원: `mock`, `simulated`, `local`, `live`, `vendor` → [2-4. RERANK_MODE 정리 참고](#2-4-rerank_mode-정리)

### 4-3. Gemini API 키 발급

1. [Google AI Studio](https://aistudio.google.com/app/apikey)에서 API Key 생성
2. `.env`에 `GEMINI_API_KEY=<키>` 및 `GOOGLE_API_KEY=<키>` 설정

### 4-4. STT 인증 설정 (Google Cloud)

1. `backend/daisoproject-sst.json` 에 서비스 계정 키 배치
2. `.env`에 `GOOGLE_APPLICATION_CREDENTIALS` 경로 설정
   - 로컬: `C:\Users\301\dev\daiso-category-search\backend\daisoproject-sst.json`
   - Docker: `/app/backend/daisoproject-sst.json` (Dockerfile에서 자동 설정)

---

## 5. 로컬 배포 진행 순서

> Windows 기준. `conda activate proj11` 후 진행.

### 5-1. Docker 인프라 시작 (ES + Qdrant + Redis)

```bash
# 프로젝트 루트에서
cd c:\Users\301\dev\daiso-category-search

# ① Docker Desktop 실행 확인

# ② ES + Qdrant + Redis 시작
docker compose up -d

# ③ 상태 확인
docker ps
curl http://localhost:9200/_cluster/health   # ES: {"status":"green/yellow"}
curl http://localhost:6333/healthz            # Qdrant: OK
docker exec daiso-category-search-redis-1 redis-cli ping   # Redis: PONG
```

### 5-2. 환경변수 설정

```bash
copy /Y .env.local .env
```

### 5-3. 검색 인덱스 구축 (최초 1회)

```bash
# products.db → ES + Qdrant 색인
python -m backend.search.indexer --source sqlite

# 확인
curl http://localhost:9200/products/_count
```

### 5-4. 백엔드 시작

```bash
# 방법 A: 스크립트 사용
start_server.bat

# 방법 B: 직접 실행
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 확인
curl http://localhost:8000/health
```

### 5-5. 프론트엔드 시작 (별도 터미널)

```bash
cd frontend
npm run dev

# 확인: http://localhost:3000
```

### 5-6. 전체 동작 확인

```bash
# API 직접 호출
curl -X POST http://localhost:8000/v1/search ^
  -H "Content-Type: application/json" ^
  -d "{\"query\": \"건전지 찾아줘\"}"
```

### 5-7. Redis 캐시 확인 및 관리

```bash
# ① API로 캐시 상태 확인 (/health 응답의 redis_cache 필드)
curl http://localhost:8000/health
# → "redis_cache": {"status": "healthy", "connected": true, "used_memory_human": "..."}

# ② 캐시 전체 삭제 (상품 데이터 변경 후 등)
curl -X DELETE http://localhost:8000/cache
# → {"status": "ok", "deleted_keys": 12}

# ③ Redis CLI로 직접 확인 (선택)
docker exec daiso-category-search-redis-1 redis-cli keys "daiso:*"
docker exec daiso-category-search-redis-1 redis-cli ttl "daiso:expand:abc123..."

# ④ 캐시 테스트 (pytest)
python -m pytest tests/test_redis_cache.py -v
# → 14 passed (graceful degradation + live Redis + key generation)
```

> ℹ️ Redis가 꺼져 있어도 검색은 정상 동작합니다 (Graceful degradation). 캐시만 비활성화됩니다.

---

## 6. 기능별 테스트 방법

> 사전 조건: `conda activate proj11` + `docker compose up -d` + `.env` 설정 완료

### 6-1. poc/ — PoC 실험 모듈

| 디렉토리 | 담당 | 내용 |
|---|---|---|
| `poc/kms/` | NLU + 키워드 확장 | Gemini 의도 분석, 키워드 확장 (운영에서 사용) |
| `poc/kdg/` | 리랭킹 PoC | Gemini 리랭킹 실험 |
| `poc/lyg/` | 하이브리드 검색 | 카탈로그 생성, 벤치마크 테스트셋) |
| `poc/stt/` | STT 어댑터 | Whisper/Google STT + 품질/정책 게이트 |
| `poc/bjy/` | 기타 실험 | 초기 실험 코드 |
| `poc/lsy/` | 기타 실험 | 초기 실험 코드 |
| `poc/intent/` | 의도 분류 | 의도 분류 실험 |

```bash
# NLU 단독 테스트
python -c "import asyncio; from poc.kms.nlu import analyze_text; print(asyncio.run(analyze_text('건전지 찾아줘')))"

# 키워드 확장 테스트
python -c "import asyncio; from poc.kms.nlu import expand_search_keywords; print(asyncio.run(expand_search_keywords('볼펜')))"

# 리랭킹 PoC (poc/kdg/)
python poc/kdg/poc_v5_experiment_phase_1.py
python poc/kdg/poc_v5_experiment_phase_1_eval.py
```

### 6-2. tests/ — pytest 테스트

```bash
# 전체 실행
python -m pytest tests/ -v

# 개별 테스트
python -m pytest tests/test_ml_rerank.py -v         # ML 리랭킹 v1
python -m pytest tests/test_ml_rerank_v2.py -v      # ML 리랭킹 v2
python -m pytest tests/test_m2_ambiguity.py -v      # 모호성 판별
python -m pytest tests/test_loadtest_rate_limiter.py -v  # Rate limiter
python -m pytest tests/test_stt_redirect_import.py -v    # STT import 검증
```

### 6-3. scripts/ — 부하 테스트·성능 측정

```bash
# 검색 API 부하 테스트
python scripts/loadtest_search.py

# 리랭킹 부하 테스트
python scripts/loadtest_rerank.py

# M1 검색 모듈 단독 테스트
python scripts/m1_test.py

# JS 부하 테스트 (k6 설치 필요)
k6 run scripts/loadtest_rerank.js
```

### 6-4. 루트 테스트 스크립트

```bash
# 통합 검색 파이프라인 테스트
python test_integrated_search.py

# STT 벤치마크 (Whisper vs Google)
python test_stt_benchmark.py

# Gemini API 연결 확인
python test_gemini_connection.py

# Fallback 모드 동작 확인
python test_fallback_mode.py
python test_fallback_mode_file.py
```

### 6-5. 로컬 vs 라이브 테스트

| 항목 | 로컬 | 라이브 |
|---|---|---|
| 환경 설정 | `copy /Y .env.local .env` | `copy /Y .env.live .env` |
| 인프라 | `docker compose up -d` | 서버 B Docker |
| API 주소 | `http://localhost:8000` | `http://3.39.6.105` |
| ES/Qdrant/Redis | localhost | 54.180.1.204 |
| 테스트 실행 | 프로젝트 루트에서 동일 명령 | 서버 A에서 동일 명령 |

---

## 7. 벤치마크 테스트 (검색 품질 평가)

> `poc/lyg/` 디렉토리의 테스트셋과 스크립트를 사용한 검색 품질 벤치마크

### 7-1. 테스트셋 파일

| 파일 | 설명 |
|---|---|
| `poc/lyg/templates/testcases.v7.tsv` | 기본 테스트셋 |
| `poc/lyg/templates/testcases.v7.clean.tsv` | 클린 테스트셋 (정제된 쿼리) |
| `poc/lyg/templates/testcases.v7.noisy.tsv` | 노이즈 테스트셋 (오타/구어체 포함) |
| `poc/lyg/data/catalog.30cat.v3.tsv` | 30개 카테고리 카탈로그 (색인 대상) |
| `poc/lyg/templates/vendors.example.yaml` | 벤더 설정 |
| `poc/lyg/templates/pipeline.example.yaml` | 파이프라인 설정 |

### 7-2. BM25 단독 벤치마크

```bash
cd poc/lyg

# 기본 테스트셋
python scripts/run_benchmark.py ^
  --vendors templates/vendors.example.yaml ^
  --pipelines templates/pipeline.example.yaml ^
  --vendor-set bm25_local ^
  --pipeline bm25_only ^
  --catalog data/catalog.30cat.v3.tsv ^
  --testcases templates/testcases.v7.tsv ^
  --out runs

# 노이즈 테스트셋 (오타/구어체)
python scripts/run_benchmark.py ^
  --vendors templates/vendors.example.yaml ^
  --pipelines templates/pipeline.example.yaml ^
  --vendor-set bm25_local ^
  --pipeline bm25_only ^
  --catalog data/catalog.30cat.v3.tsv ^
  --testcases templates/testcases.v7.noisy.tsv ^
  --out runs
```

### 7-3. BM25 + Vector + 하이브리드 벤치마크 (ivhl CLI)

> `ivhl`(intent-vector-hybrid-lab) CLI 사용. ES/Qdrant Docker 실행 필요.

```bash
cd poc/lyg

# BM25 단독
ivhl run ^
  --vendor-set ext_qdrant_elastic ^
  --pipeline-id bm25_only ^
  --catalog data/catalog.30cat.v3.tsv ^
  --testcases templates/testcases.v7.noisy.tsv ^
  --out-dir runs

# Vector (Dense) 단독
ivhl run ^
  --vendor-set ext_qdrant_elastic ^
  --pipeline-id dense_only ^
  --catalog data/catalog.30cat.v3.tsv ^
  --testcases templates/testcases.v7.noisy.tsv ^
  --out-dir runs

# 하이브리드 (BM25 + Vector + RRF Fusion)
ivhl run ^
  --vendor-set ext_qdrant_elastic ^
  --pipeline-id hybrid_rrf ^
  --catalog data/catalog.30cat.v3.tsv ^
  --testcases templates/testcases.v7.noisy.tsv ^
  --out-dir runs
```

### 7-4. 클린 테스트셋으로 벤치마크

```bash
# backend 벤치마크 모듈 사용
python -m backend.search.benchmark ^
  --testcases poc/lyg/templates/testcases.v7.clean.tsv

# 모드별 비교
python -m backend.search.benchmark --mode bm25_only
python -m backend.search.benchmark --mode dense_only
python -m backend.search.benchmark --mode hybrid
```

### 7-5. 벤치마크 결과 지표

| 지표 | 설명 |
|---|---|
| Hit@1, @3, @5, @10 | 정답이 상위 K위 안에 포함된 비율 |
| MRR | 정답 순위의 역수 평균 |
| NDCG@5, @10 | 정규화 할인 누적 이득 |
| Latency (ms) | 쿼리당 평균 응답 시간 |

---

## 8. 통합 테스트 — Vendor OFF

> **목적**: 외부 벤더 API 호출 없이 전체 파이프라인 검증 (비용 0원)

### 8-1. 환경 설정

`.env` 파일에서 다음 확인:

```env
RERANK_MODE=live
VENDOR_ENABLED=false
VENDOR_SAMPLE_RATE=0
VENDOR_MAX_CALLS_PER_MIN=0
```

> `.env.local`은 기본값이 이미 Vendor OFF 상태

### 8-2. 로컬 테스트

```bash
# ① 환경 적용
copy /Y .env.local .env

# ② 인프라 확인
docker compose up -d

# ③ 서버 시작
start_server.bat

# ④ 통합 검색 테스트 (Vendor OFF → Gemini LLM 리랭킹만 사용)
python test_integrated_search.py

# ⑤ ML 리랭킹 단독 테스트
python -m pytest tests/test_ml_rerank.py -v
python -m pytest tests/test_ml_rerank_v2.py -v

# ⑥ 모호성 + 꼬리질문 테스트
python -m pytest tests/test_m2_ambiguity.py -v

# ⑦ 벤치마크 (검색 품질 지표)
python -m backend.search.benchmark

# ⑧ API 직접 호출
curl -X POST http://localhost:8000/v1/search ^
  -H "Content-Type: application/json" ^
  -d "{\"query\": \"세탁세제\"}"
```

### 8-3. 라이브 테스트 (서버 A에서)

```bash
# ① 환경 적용
cp .env.live .env
# .env에서 VENDOR_ENABLED=false 확인

# ② 통합 테스트
python test_integrated_search.py

# ③ API 외부 호출
curl -X POST http://3.39.6.105/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "건전지 찾아줘"}'
```

### 8-4. 확인 포인트

- [x] NLU 의도 분석 정상 (timing_ms.nlu < 1000ms)
- [x] 키워드 확장 동작 (metadata.keywords.expanded 확인)
- [x] 하이브리드 검색 결과 반환 (top3 배열)
- [x] 리랭킹 적용 (metadata.rerank.selected_id 존재)
- [x] 모호 쿼리 시 꼬리질문 생성 (needs_clarification=true)
- [x] 벤더 API 호출 없음 확인 (비용 0원)

---

## 9. 통합 테스트 — Vendor ON

> **목적**: 벤더 API 리랭킹 포함 전체 파이프라인 검증 (API 비용 발생)

### 9-1. 환경 설정

`.env` 파일 수정:

```env
RERANK_MODE=vendor
VENDOR_ENABLED=true
VENDOR_SAMPLE_RATE=100
VENDOR_MAX_CALLS_PER_MIN=10
```

> ⚠️ **비용 발생**: 벤더 API(Cohere 등) 호출 시 과금됩니다. 테스트 후 반드시 OFF로 복원.

### 9-2. 로컬 테스트

```bash
# ① .env 수정 후 서버 재시작
start_server.bat

# ② 통합 테스트
python test_integrated_search.py

# ③ 리랭킹 모드 확인
curl -X POST http://localhost:8000/v1/search ^
  -H "Content-Type: application/json" ^
  -d "{\"query\": \"볼펜 찾아줘\"}"
# → metadata.rerank에 vendor 관련 정보 확인

# ④ Rate limiter 테스트
python -m pytest tests/test_loadtest_rate_limiter.py -v

# ⑤ 부하 테스트
python scripts/loadtest_rerank.py
```

### 9-3. 라이브 테스트 (서버 A에서)

```bash
# ① .env 수정 (VENDOR_ENABLED=true, RERANK_MODE=vendor)
# ② Docker 재시작
docker compose -f infra/docker-compose.app.yml restart api

# ③ 테스트
curl -X POST http://3.39.6.105/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "청소용품"}'
```

### 9-4. 테스트 후 복원

```env
RERANK_MODE=live
VENDOR_ENABLED=false
VENDOR_SAMPLE_RATE=0
VENDOR_MAX_CALLS_PER_MIN=0
```

---

## 10. 서버 A 배포 가이드 (App — 3.39.6.105)

### 10-1. 서버 초기 설정

```bash
# ① 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# ② Docker 설치
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable docker
sudo usermod -aG docker $USER
# 재로그인 필요

# ③ Nginx 설치
sudo apt install -y nginx

# ④ Node.js 18 설치
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# ⑤ Python 3.12 설치
sudo apt install -y python3.12 python3.12-venv

# ⑥ 프로젝트 클론
git clone <repo-url> ~/daiso
cd ~/daiso
```

### 10-2. 환경변수 및 Docker

```bash
cp .env.live .env
docker compose -f infra/docker-compose.app.yml up -d --build
```

확인:
```bash
curl http://localhost:8000/health
curl http://localhost:3000
```

### 10-3. Nginx 설정

```bash
sudo cp infra/nginx-host.conf /etc/nginx/sites-available/daiso
sudo ln -s /etc/nginx/sites-available/daiso /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 10-4. SSL 인증서 (도메인 있을 때)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 10-5. 서버 A 관리 명령

```bash
docker compose -f infra/docker-compose.app.yml restart     # 재시작
docker compose -f infra/docker-compose.app.yml down         # 중지
docker compose -f infra/docker-compose.app.yml logs -f api  # API 로그
docker compose -f infra/docker-compose.app.yml up -d --build # 재빌드
```

---

## 11. 서버 B 배포 가이드 (Search/Data — 54.180.1.204)

### 11-1. 서버 초기 설정

```bash
# ① 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# ② Docker 설치
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable docker
sudo usermod -aG docker $USER

# ③ ES 필수 커널 설정
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf

# ④ 파일 복사
scp -r infra/ user@54.180.1.204:~/daiso/
```

### 11-2. 서비스 시작

```bash
cd ~/daiso
chmod +x infra/start_data.sh infra/monitor.sh
./infra/start_data.sh
```

### 11-3. 상태 확인

```bash
./infra/start_data.sh status
curl http://localhost:9200/_cluster/health?pretty
curl http://localhost:6333/healthz
redis-cli ping
docker stats --no-stream
```

### 11-4. 방화벽 설정

```bash
sudo apt install -y ufw
sudo ufw allow ssh
sudo ufw allow from 3.39.6.105 to any port 9200
sudo ufw allow from 3.39.6.105 to any port 6333
sudo ufw allow from 3.39.6.105 to any port 6379
sudo ufw enable
```

### 11-5. 인덱스 구축 (서버 A에서)

```bash
# 서버 A에서 (.env에 서버 B IP 설정된 상태)
python -m backend.search.indexer --source sqlite
```

### 11-6. 메모리 모니터링

```bash
./infra/monitor.sh
watch -n 5 ./infra/monitor.sh
```

### 11-7. 서비스 설정 요약

| 서비스 | 포트 | 메모리 제한 | 비고 |
|---|---|---|---|
| Elasticsearch | 9200 | Heap 512MB, Container 1GB | `memlock` unlimited |
| Qdrant | 6333, 6334 | 512MB | 벡터 검색 |
| Redis | 6379 | `maxmemory` 50MB, Container 100MB | LRU 정책, TTL 5분 |

---

## 12. 배포 후 인프라 설정·실행·설치 순서

### 12-1. 전체 배포 순서

```
1. 서버 B (Search/Data) — 먼저
   ├── Docker 설치
   ├── vm.max_map_count 설정
   ├── docker-compose.data.yml 시작
   ├── 방화벽 설정 (서버 A IP 허용)
   └── 서비스 헬스 체크
         │
2. 서버 A (App) — 그 다음
   ├── Docker/Nginx/Python 설치
   ├── .env.live → .env 복사
   ├── docker-compose.app.yml 시작 (API + Frontend)
   ├── Nginx 설정 + reload
   ├── 검색 인덱스 구축 (→ 서버 B로 전송)
   └── 전체 동작 확인
         │
3. 검증
   ├── curl http://3.39.6.105/health
   ├── curl http://3.39.6.105/v1/search (검색 테스트)
   └── 프론트엔드 접속 http://3.39.6.105
```

### 12-2. 배포 후 체크리스트

| # | 항목 | 명령 | 기대값 |
|---|---|---|---|
| 1 | 서버 B - ES | `curl http://54.180.1.204:9200/_cluster/health` | status: green/yellow |
| 2 | 서버 B - Qdrant | `curl http://54.180.1.204:6333/healthz` | OK |
| 3 | 서버 B - Redis | `redis-cli -h 54.180.1.204 ping` | PONG |
| 4 | 서버 A - API | `curl http://3.39.6.105/health` | 200 OK |
| 5 | 서버 A - 검색 | POST `/v1/search` | top3 결과 반환 |
| 6 | 서버 A - FE | `curl http://3.39.6.105` | HTML |
| 7 | 서버 A - WS | WebSocket `/ws/stt` 연결 | 연결 성공 |

### 12-3. 장애 대응

| 상황 | 확인 | 조치 |
|---|---|---|
| 검색 없음 | ES/Qdrant 헬스 확인 | 서버 B Docker 재시작 |
| API 502 | `docker logs` | 서버 A Docker 재시작 |
| NLU 실패 | GEMINI_API_KEY 확인 | .env 키 갱신 |
| 느린 응답 | `timing_ms` 확인 | ES 힙/메모리 모니터링 |
| Redis 연결 실패 | Redis ping 확인 | 방화벽 확인, Redis 재시작 |

---

## 13. 운영 필수 모듈 실행방법

### 13-1. 검색 인덱서

```bash
python -m backend.search.indexer --source sqlite           # SQLite → ES + Qdrant
python -m backend.search.indexer --source sqlite --reset   # 삭제 후 재구축
python -m backend.search.indexer --source tsv \
  --catalog poc/lyg/data/catalog.30cat.v3.tsv              # TSV 사용
```

### 13-2. 상품 크롤러

```bash
python -m backend.database.crawler
# 크롤링 후 반드시 인덱서 재실행 필요
```

### 13-3. API 서버

```bash
# 로컬 (개발)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# 프로덕션 (gunicorn)
gunicorn backend.main:app --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 --bind 0.0.0.0:8000 --timeout 60
```

---

## 14. 기타 모듈 설치 및 실행

### 14-1. API 지연시간 측정

```bash
python measure_api_latency.py
```

### 14-2. 테스트 데이터 생성

```bash
python -m backend.database.generate_test_data
```

### 14-3. CLIP 임베딩 생성

```bash
python -m backend.database.embeddings
```

### 14-4. 카탈로그 생성 (30개 카테고리)

```bash
python poc/lyg/gen_data_30cat_200tc.py
```

### 14-5. 노이즈 테스트셋 생성

```bash
python poc/lyg/scripts/make_noisy_testcases.py
```

### 14-6. Docker 로컬 인프라

```bash
docker compose up -d       # 시작
docker compose down        # 중지
docker compose down -v     # 볼륨 포함 초기화 (데이터 삭제!)
```
