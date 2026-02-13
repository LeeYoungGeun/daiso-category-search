# CLAUDE.md - 핵심 지침 및 가이드라인

다이소 매장 키오스크에서 고객의 음성/텍스트 질의를 받아 상품 위치를 안내하는 RAG 기반 AI 검색 서비스.
파이프라인: **STT → 의도분석 → 키워드 추출/확장 → Hybrid 검색(BM25+Vector) → 리랭킹 → 위치안내 + QR 인계**

## 🏗 Architecture (Current State)

- **언어**: Python 3.12 (FastAPI 기반)
- **로직**: LangGraph 기반의 상태 머신 파이프라인
- **인프라**: 2-Server 분리 (App Server / Data Server) -> `infra/` 및 `docker-compose.*.yml` 참조

### 주요 모듈 (Key Modules)

| 모듈 | 경로 | 역할 |
|---|---|---|
| **Pipeline** | `backend/logic/integrated_search.py` | 전체 검색 워크플로우 총괄 (M2 애매함 처리 포함) |
| **NLU** | `poc/kms/` | Gemini 2.0 Flash 기반 의도분석, 키워드 추출/확장 |
| **Search** | `backend/search/` | `hybrid.py` (ES+Qdrant), `cache.py` (Redis), `indexer.py` (색인) |
| **Rerank** | `backend/ml/rerank_service.py` | `mock`/`simulated`/`local`/`vendor` 모드 지원 리랭커 |
| **STT** | `poc/stt/` | Google Cloud STT (Primary) + Whisper base (Fallback) 어댑터 및 Quality Gate |
| **Logic** | `backend/logic/` | `ambiguity.py` (애매함 판정), `reranker.py` (LLM 리랭크 로직) |
| **Frontend** | `frontend/` | Next.js 14 기반 키오스크 UI |
| **Database** | `products.db` | 단일 데이터 소스 (SQLite) -> ES/Qdrant 색인 원천 |

## 🛠 Tech Stack

- **Backend**: Python 3.12, FastAPI, LangGraph, Pydantic v2
- **Frontend**: Next.js 14, Tailwind CSS, Lucide React
- **LLM**: Gemini 1.5/2.0 Flash (의도분석, 키워드, 리랭킹)
- **STT**: Google Cloud Speech-to-Text v1 (Streaming, Primary), Whisper base (Fallback)
- **Search**: Elasticsearch 8.x (BM25), Qdrant 1.9.x (Vector), Redis 7.x (Cache)
- **Cache**: Redis 기반 키워드/검색결과 캐싱 (TTL 5분, Graceful Degradation)

## 💻 Build & Run Commands

### 📋 Backend
```bash
# 의존성 설치
pip install -r requirements.txt

# 서버 실행 (로컬)
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 전체 테스트 실행
python -m pytest tests/
```

### 📋 Frontend
```bash
cd frontend
npm install
npm run dev
```

### 📋 Infra/Docker
```bash
# 인프라 시작 (ES, Qdrant, Redis)
docker compose -f docker-compose.data.yml up -d

# 인덱싱 (최초 1회)
python -m backend.search.indexer --source sqlite
```

## 📋 Verified Results (PoC 성능 지표)

- **의도분석**: 정확도 97%
- **검색 Hit@5**: 98.9% (Hybrid Search)
- **리랭킹**: 정확도 93.4%
- **전체 레이턴시**: 목표 2.5초 내외 (Redis 캐시 적중 시 1초 미만)

---

## ⚠️ AI 및 개발자 주의사항 (AI Guideline)

> [!IMPORTANT]
> **이 프로젝트는 Node.js Migration 계획이 있었으나 현재 Python 기반으로 완성되었습니다.**
> `plans/architecture-plan.md` 등에 기재된 Node.js 전환 계획은 **[ARCHIVED]** 상태이며, 현재 모든 로직은 Python `backend/` 폴더에 구현되어 있습니다.

- **TDD 실천**: `tests/` 에 테스트 코드를 먼저 작성하고 `pytest`를 통해 검증하십시오.
- **Graceful Degradation**: Redis나 ES가 꺼져 있어도 SQLite Fallback을 통해 기본 검색은 동작해야 합니다.
- **Environment**: `.env.local` (로컬 데이터), `.env.live` (운영 데이터) 환경 분리에 주의하십시오.
