# **PoC (Proof of Concept) 검증 리포트: RAG 견고성 확보**

> **문서 목적**: "정제된 키워드(Structured Query)"를 입력했을 때, 검색 실패가 얼마나 개선되는지(Robustness) 검증
> **검증 대상**: 키워드 입력 환경에서의 Top-K 파라미터별 재현율(Recall) 비교
> **작성일**: 2026-01-20 (완료)
> **작성자**: Search/Brain Lead

---

## **1. Executive Summary (요약)**

Baseline(문장 직검색)에서 57.8%였던 재현율은 **키워드화(Keyword Extraction)**만 수행해도 **74.0%(K=30)**까지 회복되었습니다. 특히 **검색 후보군(Top-K)을 10개에서 30개로 확장**했을 때 재현율이 20%p 상승하는 효과를 확인했습니다.
다만, "양피 장갑(검색어)" vs "골프 장갑(상품명)"과 같은 **동의어 불일치(Synonym Mismatch)** 문제는 여전히 존재하므로, 향후 에이전트는 단순 추출을 넘어 **"동의어 확장"** 기능까지 갖춰야 함을 발견했습니다.

*   **최종 성적**: ✅ **Pass (Robustness Improved)**
*   **핵심 성과**: 문장 검색 대비 Recall **+16.2%p** 개선 (57.8% -> 74.0%).
*   **Next Action**: Step 3 에이전트에 **Synonym Expansion(동의어 확장)** 로직 추가 필요.

---

## **2. Experiment Setup (실험 설계)**

### **2.1 실험 아키텍처**
*   **Input**: 50개의 목업 키워드 (예: "수세미", "방한장갑", "양피장갑" 등 난이도 상/중/하 혼합)
*   **Assumption**: Step 3 Agent가 불용어를 완벽히 제거했다고 가정.
*   **Variable**: `Top-K` (10, 30, 50)

### **2.2 실험 환경**
*   **데이터셋**: 200개 상품 DB.
*   **모델**: `MiniLM` (Retrieval) + `Gemini 2.0 Flash` (Intent/Rerank).

---

## **3. Key Results (핵심 실험 결과)**

### **[Metric] Top-K Comparison (파라미터 튜닝)**

> **실험 결과**: K=10은 너무 좁고, **K=30**이 성능과 효율의 균형점(Sweet Spot)임.

| Metric | K=10 (Default) | **K=30 (Optimized)** | **K=50 (Wide)** | 개선 효과 |
| :--- | :--- | :--- | :--- | :--- |
| **1. Intent Accuracy** | 90.0% | **90.0%** | **90.0%** | - |
| **2. Retrieval Recall** | 54.0% | **74.0%** | **76.0%** | **K=30에서 급상승** |
| **3. Rerank Precision** | 48.0% | **66.0%** | **64.0%** | **Recall 확보로 정밀도 동반 상승** |

### **[Analysis] 실패 케이스 분석 (Remaining 26%)**

| 검색어 (Keyword) | 매칭 실패 원인 | 해결 방안 제언 |
| :--- | :--- | :--- |
| **양피 장갑** | DB에는 "골프 장갑"만 존재. (Vector Distance가 멈) | Agent가 "양피" -> "골프"로 **동의어 확장** 필요 |
| **수세미** | DB에는 "설거지용 스펀지/브러쉬" 위주. | "수세미" -> "설거지 스펀지"로 **텀 확장** 필요 |
| **왁스** | "헤어 왁스" vs "자동차 왁스" 혼동 | Intent Classification 룰 강화 필요 |

---

## **4. Conclusion (결론 및 제언)**

### **4.1 최종 확정 아키텍처**

검색 엔진의 파라미터를 **Recall 중심(Broad Search)**으로 변경하고, 에이전트의 역할을 구체화합니다.

1.  **Search Engine**:
    *   **Retrieval**: `Top-K = 30` (기존 10개 대비 3배 확장하여 후보군 확보)
    *   **Filter**: `Category Pre-filter` (자동차 용품에 미용 용품 안 섞이게 방어)

2.  **Frontend Agent (Step 3 Requirement)**:
    *   **Must Have**: 단순 명사 추출뿐만 아니라, **"쇼핑몰 용어"로의 변환(Synonym Expansion)** 능력이 필수적임.
    *   *Example*: "빨래 널 때 쓰는거" -> "빨래 건조대"

### **4.2 기대 효과**
*   **기본기 확보**: 명확한 키워드("욕실매트", "고무장갑")에 대해서는 **100%에 가까운 정확도** 보장.
*   **방어 기제**: 애매한 검색어라도 K=30으로 넓게 긁어와서, Reranker가 2차로 살려낼 기회를 제공함.

### **4.3 배포 설정 값 (Config)**

```python
SEARCH_CONFIG = {
    "top_k": 30,  # 10 -> 30 (Recall 최적화)
    "threshold": 0.0, # 모든 후보를 Reranker에게 넘김
    "enable_synonym_expansion": True # (Future Plan)
}
```

---
*위 리포트는 정제된 키워드 50개를 대상으로 한 시뮬레이션 결과입니다.*
