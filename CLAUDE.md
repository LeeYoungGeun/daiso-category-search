# TDD Absolute Rules

1. **Red First**: Write a failing test before any implementation code.
2. **Green Minimal**: Write only the minimum code needed to pass the test.
3. **One Step**: Complete one Red→Green cycle before proceeding to the next.

다이소 매장 키오스크에서 고객의 음성/텍스트 질의를 받아 상품 위치를 안내하는 RAG 기반 AI 검색 서비스.
파이프라인: **STT → 의도분석 → 키워드 추출/확장 → Hybrid 검색(BM25+Vector) → 리랭킹 → 위치안내 + QR 인계**

## Architecture

- **현재 상태**: Python(FastAPI) PoC — 각 기능이 `poc/` 하위에 별도 모듈로 분리됨 (미통합)
- **목표 상태**: Node.js/TypeScript 모노레포 — 논리적 MSA + 물리적 모놀리식 런타임
- **상세 계획**: `plans/architecture-plan.md` 참조

### Key Modules (현재 PoC)

| Module | Path | Role |
|--------|------|------|
| STT | `poc/stt/` | Whisper + Google Cloud STT 어댑터, Quality Gate, Policy Gate |
| NLU | `poc/kms/` | Gemini 2.0 Flash 기반 의도분석, 키워드 추출/확장 |
| Search | `poc/lyg/` | BM25(Elastic) + Vector(Qdrant) + Hybrid RRF Fusion |
| Rerank | `poc/kdg/` | Gemini 2.0 Flash LLM 리랭킹 |
| Intent Gate | `poc/intent/` | In/Out-of-scope 판별 |
| Location/QR | `poc/bjy/` | 위치 매핑 + QR 핸드오버 |
| Agent Graph | `backend/logic/` | LangGraph 5-node 워크플로우 (부분 통합) |
| Frontend | `frontend/` | Next.js 14 키오스크 UI |
| Database | `backend/database/` | SQLite + CLIP 임베딩 |

## Tech Stack

- **Backend (현재 PoC)**: Python 3.x, FastAPI, LangGraph
- **Backend (목표)**: Node.js, TypeScript strict, Express/Fastify
- **Frontend**: Next.js 14, React 18, Tailwind CSS
- **LLM**: Gemini 2.0 Flash (의도분석, 키워드 추출, 리랭킹)
- **STT**: Google Cloud Speech-to-Text v1 (streaming), Whisper medium (fallback)
- **Search**: Elasticsearch (BM25), Qdrant (Vector), RRF Fusion
- **Embedding**: paraphrase-multilingual-MiniLM-L12-v2
- **DB**: SQLite (현재) → PostgreSQL (목표)
- **Cache**: Redis
- **Deploy**: AWS Lightsail + Docker Compose + Nginx

## Development Rules — CRITICAL

### TDD 강제 규칙 (5줄)

- **테스트 없이 구현 코드 먼저 작성 금지**
- **실패(Red) 확인 없이 구현 금지**
- 구현 중 **테스트 코드 수정 금지** (테스트 통과 후 리팩토링 단계에서만 허용)
- 테스트 커버리지 **80% 이상** (핵심: nlu/retrieval/rerank는 더 높게 권장)
- 배포 금지 조건: 테스트 미통과, 테스트 누락, 테스트를 수정해서 억지 통과

### TDD 순서 (고정)

1. 테스트 코드 작성 → 성공 기준을 코드로 고정
2. 테스트 실행 → 실패 확인 (Red)
3. 최소 구현 (Green)
4. 전체 테스트 재실행 → 통과 확인
5. 리팩토링
6. 회귀 테스트 재실행 → 항상 Green 유지

### 병합(merged) 오버헤드 최소화 규칙 (5줄)

- **원칙 A**: 로컬/파일럿 단계에서는 `api-gateway` 중심의 **단일 런타임(또는 최소 2~3개)** 로 합쳐 실행 (모듈은 내부 패키지로 유지)
- **원칙 B**: 서비스 간 통신을 HTTP로만 강제하지 않고, 병합 모드에서는 **in-process 호출(모듈 import)** 로 전환 가능하도록 어댑터 계층 구성
- **원칙 C**: 큐/배치/스케줄링은 병합 모드에서 **단일 워커**만 실행되도록 락(리더 선출/redis 락) 적용
- **원칙 D**: `docker-compose`의 profile(`merged`, `msa`)로 실행 형태를 고정하고, 병합/로컬 테스트는 기본적으로 `merged` 프로파일만 허용
- **원칙 E**: 개발 서버(핫리로드)도 병합 모드에서는 **단일 dev 서버** 사용, 포트는 `api-gateway` 1개만 외부 노출

### 작업 지시 템플릿

```
목표: (한 줄로)
성공기준: (Jest 테스트가 Red→Green, 테스트 수정 금지)
범위: (수정 가능한 폴더/파일)
금지: 구현 먼저 작성 금지. 반드시 테스트 → 실패 확인 → 구현.
명령: (실행할 테스트/빌드 명령)
```

## Build & Run Commands

### Frontend (현재)

```bash
cd frontend && npm install
cd frontend && npm run dev      # dev server on :3000
cd frontend && npm run build    # production build
cd frontend && npm run lint     # lint check
```

### Backend (현재 PoC — Python)

```bash
pip install -r requirements.txt
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000  # FastAPI server
```

### Test Commands (목표 — Node.js 전환 후)

```bash
npm test                    # 전체 테스트
npm test -- --coverage      # 커버리지 포함
npm run lint                # ESLint
npm run typecheck           # TypeScript strict
```

## Code Style

- TypeScript strict mode 필수
- ESLint + Prettier 적용
- 커버리지 목표: 80% 이상 (nlu/retrieval/rerank는 더 높게)
- 모든 API 응답은 Zod 스키마로 검증

## Environment Variables

- `.env` 파일은 **절대 커밋 금지** — `.env.example` 참조
- 필수 키: `GEMINI_API_KEY`
- Google STT: `backend/daisoproject-sst.json` (서비스 계정 JSON)
- 추가 키 (목표): `DATABASE_URL`, `REDIS_URL`, `ELASTIC_URL`, `QDRANT_URL`

## Repository Structure

```
repo-root/
  backend/              # Python PoC 백엔드 (현재)
    logic/              # LangGraph agent, NLU, prompts, schemas
    database/           # SQLite DB, embeddings, category matcher
  frontend/             # Next.js 키오스크 UI
  poc/                  # 기능별 PoC 모듈 (미통합)
    stt/                # STT 어댑터 + 게이트
    kms/                # NLU + 키워드 추출
    kdg/                # 리랭킹 실험
    lyg/                # Hybrid 검색 벤치마크
    bjy/                # 위치안내 + QR
    intent/             # 의도분석 게이트
  data/                 # 테스트 오디오 파일
  docs/                 # 프로젝트 문서, 보고서
  plans/                # 아키텍처 계획
  CLAUDE.md             # 이 파일
```

## API Contract (핵심)

### POST /v1/search

- Request: `{ storeId, inputType, query, sessionId }`
- Response: `{ requestId, isInScope, top3[], top1Handover, timingMs }`
- Out-of-scope: `isInScope=false` → 안내 메시지/FAQ

### WebSocket /ws/stt

- `start` → 세션 시작 (meta: run_id, test_id)
- `audio` → PCM base64 청크
- `interim` ← 중간 결과
- `final` ← 최종 결과 + confidence + latency

## Merge & Deploy Rules

- **배포 전 필수**: 단위 테스트 + 통합 테스트 전체 Green
- **merged 프로파일**: 애플리케이션 런타임 1~3개 + 인프라(Elastic/Qdrant/Redis/DB)
- **프로세스 난립 금지**: 병합 모드에서 단일 런타임 + in-process 호출
- **배포 금지 조건**: 테스트 미통과, 테스트 누락, 환경변수 불일치, 스키마 불일치
- **검증 필수**: 병합 후 로컬 통합 실행 시, 프로세스 수/컨테이너 수가 목표 범위 초과 시 배포 금지

## PoC Verified Results — 파이프라인 6단계 성능지표

### 파이프라인 단계별 성능

1. **STT (Speech-to-Text)**
   - Google Cloud API: Keyword Hit 69.12%, Latency 1.2초
   - Whisper medium: Keyword Hit 80%, Latency 7.2초 (fallback 후보)

2. **의도분석 (Intent Classification)**
   - 선정 모델: Gemini 2.0 Flash
   - 정확도(Accuracy): **97.0%**, 정밀도(Precision): 91.2%, 재현율(Recall): 100%, F1 Score: 95.4%
   - 속도: 0.70초/건

3. **의도(키워드) 추출 (Keyword Extraction)**
   - 선정 모델: Gemini 2.0 Flash
   - 정확도(Accuracy): **89.0%** (목표 90% 근접)
   - 속도: 0.68초/건, 토큰 사용량: 126토큰/건
   - 평가 데이터: 596건 (직접 검색형 142건 + 문제 해결/묘사형 등 454건)

4. **검색 (Hybrid Search: BM25 + Vector + Fusion)**
   - CLEAN 테스트: Hit@1 약 81%, Hit@5 약 **99%**, Hit@10 100%
   - NOISY 테스트 (함정 키워드): Hit@1 약 80%, Hit@5 약 **98%**, Hit@10 99%
   - 속도: BM25 0.033초, Dense 0.338초, Hybrid RRF 0.388초/쿼리
   - 테스트케이스: 86개, 상품 개수: 460개
   - **결론**: 하이브리드 검색이 Hit@5 최우수 성능, NOISY 환경에서도 약 2% 하락으로 견고성 확인

5. **리랭킹 (Re-ranking)**
   - 선정 모델: Gemini 2.0 Flash (LLM)
   - 정확도(Accuracy): **93.4%** (57/61), 재현율(Recall): 94.4%, 정밀도(Precision): 94.4%
   - MRR: 0.9481, 속도: 887.0ms
   - 평가 데이터: 61개 케이스 (유의어, 의도, 시각 묘사, 오타, 함정 등 5개 시나리오)
   - 복합적인 문맥 추론 및 오타 복구 능력 확인 완료

6. **상품 위치 안내 (Location Guidance + QR Handover)**
   - QR 생성 및 모바일 인계: **100%** 성공
   - 데이터: 602개 카테고리 및 매장 위치 좌표 DB
   - 기술: Cross-Device Context Handover, Real-time Rendering, State Preservation
   - 미결 과제: 실제 위치 기반 실내 내비게이션 기능 및 현장 PoC

### 핵심 성능 요약

- **의도분석**: 97% 정확도 (목표 90% 초과 달성)
- **검색**: Hit@5 98% (목표 97% 초과 달성)
- **리랭킹**: 93.4% 정확도
- **견고성**: NOISY 테스트 시 성능 하락 약 2% 수준으로 실전 적용 가능

## Key Design Decisions

1. **Hybrid Search K=30**: PoC에서 K=10→K=30으로 Recall 72%→92% 개선 확인. K=50과 차이 없어 K=30이 최적점.
2. **의미 추출 필수**: Raw sentence 벡터 검색은 Recall 57.8%로 실패. 반드시 키워드 추출 후 검색.
3. **Intent Classifier 유지**: 앞단 에이전트 완성도가 높아질 때까지 검색 내부 Rule-Set 유지 (Safety Net).
4. **어댑터 패턴**: 서비스 간 통신을 merged(in-process) / msa(HTTP) 모드로 전환 가능하게 설계.

## Milestones (프로젝트 문서 기준)

1. **M0: 병합/통합 실행 안정화** — 모노레포 구성 → 서비스 TDD 구현 → API Gateway 통합 → Frontend → e2e 3케이스 Green
2. **M1: 하이브리드 검색 지표 고정** — hit@k/mrr/ndcg 자동 측정, 벤치마크 템플릿화
3. **M2: 리랭킹/애매함 처리 고도화** — 애매함 판정, 꼬리질문, 2회 실패 Fallback
4. **M3: Lightsail 운영 안정화** — 로그/모니터링, 장애 Fallback, 비용 상한

## Additional Instructions

- 프로젝트 문서: `docs/프로젝트 개요 및 개발 방법.md` 참조
- 아키텍처 계획: `plans/architecture-plan.md` 참조
- 변경 이력: `CHANGELOG.md` 참조
- 실패 케이스 분류: `failure_cases.md` 참조
