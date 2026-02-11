# **PoC (Proof of Concept) 검증 리포트: RAG 대규모 Baseline (문장형 쿼리)**

> **문서 목적**: 앞서 최적화된 **Step 4~6(검색/리랭킹/필터)** 파이프라인이 **"자연어 문장(Raw Sentence)"** 입력 환경에서도 유효한지 검증 (Integration Test).
> **검증 대상**: 문장형 쿼리에 대한 검색 재현율(Recall) 및 벡터 희석(Vector Dilution) 현상 확인
> **작성일**: 2026-01-20
> **작성자**: Search/Brain Lead

---

## **1. Executive Summary (요약)**

Unit Test(단어 검색)에서 완벽했던 최적화 모델(`MiniLM` + `Pre-filter` + `Gemini Rerank`)을 **200개 상품 규모의 실전 환경(문장 검색)**에 투입한 결과, **재현율(Recall)이 57.8%로 급락**하는 현상을 발견했습니다.

1.  **원인**: 문장 내 불필요한 서술어("추천해줘", "찾아줘" 등)가 핵심 키워드("고무장갑")의 벡터값을 희석시킴.
2.  **결과**: Core Engine(Step 4~6)은 정상이지만, **Input Data(쿼리)의 퀄리티 문제**로 인해 검색 실패.
3.  **결론**: 검색 엔진 진입 전, 사용자의 발화에서 핵심 의도와 키워드만 발라내는 **Meaning Extraction Agent (Step 3)** 도입이 필수적임.

---

## **2. Experiment Setup (실험 설계)**

### **2.1 데이터셋 구성 (Dataset)**
*   **전체 데이터**: 총 200개의 상품 (Large Scale 확장)
    *   **구성**: 기존 12개 카테고리 외 다양한 잡화 포함 (다이소 실제 상품군 모사)
*   **테스트 쿼리**: **자연어 문장 45개** (Integration Query)
    *   **예시**: "설거지할 때 끼는 안 미끄러지는 고무장갑 추천해줘" (의도 + 수식어 + 키워드 + 서술어 혼합)
*   **가정 (Assumption)**:
    *   **Step 1~2 (STT/System Check)**: 통과했다고 가정.
    *   **Step 3 (Keyword Extract)**: **없음 (Direct Input)**.
    *   **Step 4~6 (Core Search)**: Report 1에서 최적화된 설정(`MiniLM`, `Pre-filter`, `Gemini Rerank`) 사용.

### **2.2 실험 로직**
*   **Flow**: `Raw Sentence` -> `Intent Classifier(Pre-filter)` -> `Vector Search(MiniLM)` -> `Rerank(Gemini)`
*   **가설**: "MiniLM이 한국어 성능이 좋으므로 문장 전체를 넣어도 핵심을 잘 잡을 것이다?" (검증 포인트)

### **2.3 평가지표 (Metrics)**
1.  **Intent Accuracy**: 문장에서 카테고리를 맞췄는가?
2.  **Retrieval Recall**: Top-10 안에 정답 상품이 있는가?
3.  **Rerank Precision**: 최종 1등이 정답인가?

---

## **3. Key Results (핵심 실험 결과)**

### **Step 1~6 통합 성능 (Baseline Performance)**

> **실험 목적**: 전처리(키워드 추출) 없는 생 문장 검색의 한계 측정

| 평가 항목 | 성공 횟수 (N=45) | 성공률 (%) | 판정 |
| :--- | :--- | :--- | :--- |
| **의도 분류 (Intent)** | 39 / 45 | **86.7%** | ⚠️ **Warning** (서술어 간섭) |
| **검색 재현율 (Recall)** | 26 / 45 | **57.8%** | ❌ **Critical Fail** |
| **최종 정밀도 (Precision)** | 26 / 45 | **57.8%** | ❌ **Critical Fail** |

### **실패 원인 분석: 벡터 희석 (Vector Dilution)**

| 입력 쿼리 (Sentence) | 검색 결과 (Top-1) | 실패 원인 |
| :--- | :--- | :--- |
| "그립감 좋은 **양피 장갑** 추천해줘" | **세차 타월** (유사도 0.61) | '양피'보다 '닦는 행위/추천' 문맥에 벡터가 쏠림 |
| "화장실 앞에 깔아두는 **매트**" | **바디워시** (유사도 0.58) | '매트' 비중 감소, '화장실' 위치 정보가 지배적임 |
| "**변기** 안쪽 닦는 청소 **솔**" | **변기 세정제** (유사도 0.72) | '솔(Brush)' 형상보다 '청소/변기' 목적성이 강조됨 |

*   **Insight**: 문장이 길어질수록 핵심 Entity("장갑", "솔")의 벡터 점유율이 $1/N$로 줄어들며, 대신 "추천", "용도" 등 일반적인 단어들의 노이즈가 증폭됨.

---

## **4. Conclusion (결론 및 아키텍처 수정)**

### **4.1 최종 진단**
*   **Core Engine (Step 4~6)**: 정상 (Report 1 검증 완료).
*   **Bottleneck**: **Input Layer**. 검색 엔진에게 "문장"을 그대로 던지는 것은 비효율적임.
*   **Solution**: 검색 엔진은 기계어(Keyword)를 좋아하므로, 중간에서 번역해줄 **Agent**가 필요.

### **4.2 수정된 아키텍처 제안 (Step 3 추가)**

기존 파이프라인에 **Step 3 (Meaning Extraction)** 단계를 공식 추가합니다.

*   **Before (Baseline)**:
    *   `문장` -> `Intent Filter` -> `Vector Search` -> `Fail`
*   **After (Robustness V2)**:
    *   `문장` -> **`[Step 3] Meaning Extraction Agent`** -> `{"키워드": "고무장갑", "의도": "주방"}` -> `Vector Search` -> `Success`

### **4.3 Next Steps: Agent 도입 검증**
이 "Meaning Extraction Agent"를 도입했을 때 실제로 Recall이 57%에서 90% 이상으로 복구되는지 검증합니다.

*   **연결 문서**: `RAG_ROBUSTNESS_POC_REPORT.md`
*   **검증 목표**:
    1.  LLM을 이용해 문장에서 불용어 제거 및 핵심 키워드 추출.
    2.  추출된 키워드로 검색 시 성능 변화 측정.

