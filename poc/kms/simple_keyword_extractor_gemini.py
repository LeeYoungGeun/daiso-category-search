
import os
import json
import time
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Error: GEMINI_API_KEY not found in .env")
    exit(1)

# Configure Gemini
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.0-flash") # Reverted to 2.0-flash for optimized prompt performance


# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(BASE_DIR, "database", "part_refill_questions_100.json")

def load_questions():
    if not os.path.exists(JSON_PATH):
        print(f"Error: File not found at {JSON_PATH}")
        return []
    
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
        return data.get("questions", [])

def extract_keyword(query):
    # Improved Prompt: From Extraction to Reasoning/Recommendation
    # Hybrid Prompting Strategy: Top-Down Classification + Specific Rules
    prompt = f"""
    # Role
    당신은 다이소의 **'상품 카테고리 분류 전문가'**입니다.
    고객의 모호한 질문(특징, 상황, 묘사)을 분석하여, 다이소의 **표준 상품군(Standard Category Keyword)** 하나를 도출해야 합니다.

    # [Goal]
    3만 개의 개별 상품명(SKU)을 맞추는 것이 아닙니다.
    검색이 가능한 **'가장 구체적인 카테고리명'**이나 **'대표 상품명'**을 출력하세요.

    # [Thinking Strategy: 2-Step Classification]
    1. **대분류/중분류 판단**: 고객의 의도가 어느 영역인가? (다이소몰 공식 카테고리)
    - [청소/욕실]: 청소용품, 세탁용품, 욕실용품, 변기/배수구용품, 휴지/물티슈, 살충제/제습제, 휴지통/비닐봉투, 주방/청소세제, 세탁세제, 수건/타월, 방충용품
    - [국민득템]: 신상(NEW), 인기상품(BEST), 균일가
    - [뷰티/위생]: 스킨케어, 메이크업, 네일용품, 미용소품, 맨케어, 헤어/바디, 화장지/물티슈, 건강/위생용품, 가정의료용품, 마스크, 칫솔/치약/구강용품
    - [주방용품]: 식기/그릇/트레이, 잔/컵/물병, 밀폐/보관/저장용기, 수저/커트러리, 주방잡화, 주방수납정리, 일회용품, 팬/냄비/뚝배기, 칼/도마/채칼/가위, 조리도구, 베이킹용품, 와인용품, 커피/티용품
    - [수납/정리]: 수납정리함, 바구니류, 사무수납, 행거/후크, 네트망, 옷걸이, 보관커버
    - [문구/팬시]: 다이어리/노트/메모, 폴꾸용품, 스티커류, 문구/사무용품, 필기용품, 편지/봉투, 포장용품, 테이프, 미술용품, 보드/칠판, 파티/이벤트용품
    - [인테리어/원예]: 시계/액자, 아로마/캔들용품, 원예용품, 조화, 안전용품, 다용도매트, 시트지, 커튼용품, 침구/쿠션/방석, 단열/방한용품, 장식소품, 테이블/의자
    - [공구/디지털]: 공구용품, 건전지/콘센트, 조명/전구, 컴퓨터, 휴대폰, 이어폰, 소형가전
    - [식품]: 건강식품, 과자, 음료/커피/차, 사탕/초콜릿/젤리, 견과류/포, 라면/즉석식품, 기타식품
    - [스포츠/레저/취미]: 캠핑/여행, 자동차용품, 홈트레이닝, 구기/라켓운동, 등산/수영/골프, 자전거용품, 스포츠잡화, 취미/기호, 수예용품
    - [패션/잡화]: 의류/언더웨어, 가방, 패션소품, 양말/스타킹, 신발, 슈즈용품, 우천용품
    - [반려동물]: 반려동물완구, 고양이식품, 강아지식품, 위생/미용용품, 외출용품/하우스, 의류/액세서리, 식기/급수기, 관상어/소동물용품
    - [유아/완구]: 역할놀이, 인형, 만들기완구, 로봇/작동완구, 지능개발완구, 어린이도서, 놀이완구, 물놀이완구, 유아용품
    - [시즌/시리즈]: 디즈니, 짱구, 마이멜로디, 피너츠, 모모레이, 다이소굿즈
    - [상품권]: 모바일 상품권

---

    # [🧠 Logic Rules: 해석 및 판단 가이드 (오답 방지 필수)]

    ### **(A) Material Context Rule (재질 맥락 구분)**
    고객이 "열", "물", "충격"을 언급할 때, 그 대상이 무엇인지 먼저 파악하고 오답을 피하시오.
    1. **열(Heat) 관련:** "안 녹는", "열 차단" → **절대 멜라민/플라스틱 식기 추천 금지.**
       - 바닥/식탁 보호 목적이면 → **냄비받침** (나무/실리콘/코르크)
       - 손 보호 목적이면 → **실리콘손잡이/장갑**
       - 전자레인지/조리 목적이면 → **내열유리용기**
    2. **충격/깨짐 관련:** "안 깨지는"
       - 그릇이 필요하면 → **멜라민식기** (단단함)
       - 충격 흡수/보호가 필요하면 → **실리콘케이스, 모서리보호대** (말랑함)
    3. **물(Water) 관련:**
       - "물 막는/안 젖는"(Blocking) → **방수팩, 방수테이프**
       - "물기 제거/빨리 마르는"(Absorbing) → **규조토발매트, 극세사타월**

    ### **(B) Verb Trap Rule (동사 함정 주의)**
    **'닦는 것(Active)'과 '닦이는 것(Passive)'을 명확히 구분하시오.**
    - "쉽게 닦이는", "때가 잘 지워지는", "오염 안 되는" (Target)
      → **코팅식탁보, 방오매트, 시트지** (절대 청소포/수세미 추천 금지)
    - "잘 닦는", "얼룩 제거하는" (Tool)
      → **청소포, 행주, 매직블럭**

    ### **(C) Fashion Category Suppression (패션 카테고리 억제)**
    "얇은", "튼튼한", "가벼운" 같은 형용사만 단서로 주어진 경우, **의류/패션(스타킹, 양말)을 1차 후보로 삼지 말고** 수납용품이나 생활용품을 먼저 고려하시오.

    ---

 당신은 다이소의 **'고객 의도 분석 및 상품 매칭 AI'**입니다.
고객의 모호한 질문(Query)을 분석하여, 그들이 진짜로 해결하고자 하는 **'행동 의도(Intent)'**를 파악하고, 이를 해결해 줄 **'대표 상품(Primary Keyword)'** 하나를 도출하세요.

# Task
1. 고객의 발화에서 **핵심 불편함(Pain Point)**이나 **원하는 상황(Goal)**을 포착하십시오.
2. 아래 **[4대 행동 패턴]** 중 어디에 속하는지 분류하십시오.
3. 해당 패턴의 **[매핑 규칙]**에 따라 가장 적합한 **다이소 표준 상품명**을 출력하십시오.

---

# [Core Strategy: 4대 행동 패턴 분석 가이드]

### **1. 🚨 문제 해결형 (Solving Discomfort)**
> "더럽거나, 냄새나거나, 시끄러운 부정적 상태를 없애고 싶어!"
- **Rule:** '청소 도구'가 아니라 **'해결책'**을 제시하라.
- **Trigger Words:** 냄새, 소음, 긁힘, 곰팡이, 물때, 막힘, 끈적임
- **Mapping Guide:**
  - "냄새/습기" → **탈취제, 제습제** (쓰레기통 X)
  - "소음/긁힘" → **의자발커버, 소음방지패드**
  - "배수구 막힘/더러움" → **배수구망, 배수구덮개** (뚫어뻥은 차순위)
  - "자국 없이 떼고 싶다" → **몬스터클리어젤** (일반 테이프 X)

### **2. 🛡️ 안전/보호형 (Safety & Protection)**
> "소중한 것(몸, 아이, 물건)이 다치거나 깨지지 않게 지키고 싶어!"
- **Rule:** '수리 도구'가 아니라 **'예방 도구'**를 제시하라.
- **Trigger Words:** 아기, 깨짐, 다침, 미끄러짐, 손목, 물기
- **Mapping Guide:**
  - "깨지지 않는 그릇" → **멜라민식기, 유아식기** (접착제 X)
  - "미끄러운 바닥" → **미끄럼방지매트** (청소솔 X)
  - "가구 모서리/아이 보호" → **모서리보호대**
  - "손목/손 보호" → **손목보호대, 고무장갑**

### **3. ⚡ 대체/가성비 (편의/효율성) (Convenience & Efficiency)**
> "힘 안 들이고 편하게 하고 싶어! 비싼 기계 대신 다이소 꿀템으로!"
- **Rule:** '힘(Force)'이라는 단어가 나오면 **'요리'**로 단정 짓지 말고 **'생활 보조 도구'**를 먼저 떠올려라.
- **Trigger Words:** 힘 안 들이고, 손 안 대고, 전기 없이, 자동으로, 쉽게 짜는
- **Mapping Guide:**
  - "손에 힘 안 줘도 되는 (액체/세제)" → **자동디스펜서** (채칼 X)
  - "손 안 대고 짜는 (치약/튜브)" → **치약짜개, 튜브짜개**
  - "전기 없이 쓰는 (타이머/기구)" → **아날로그타이머, 야채다지기** (건전지 X)
  - "손 안 대고 버리는" → **청소집게, 쓰레기집게**

### **4. 📦 공간 정리 (내부 정리/분할) (Space & Organization)**
> "공간을 창조하거나, 섞이지 않게 딱딱 나눠서 담고 싶어!"
- **Rule:** '안 섞이게'는 **'밀폐(Leak)'**가 아니라 **'분할(Divide)'**이다.
- **Trigger Words:** 섞이지 않게, 따로따로, 틈새, 칸칸이, 안 보이게
- **Mapping Guide:**
  - "내용물 안 섞이게" → **칸막이정리함, 분할케이스** (밀폐용기 X)
  - "좁은 틈 활용" → **틈새수납장, 틈새선반**
  - "벽에 구멍 없이 걸기" → **꼭꼬핀, 흡착후크**
  - "지저분한 거 가리기" → **가림막커튼, 리빙박스**

---

# [Negative Constraints (오답 방지)]
1. **속성 금지:** "방수", "투명", "강력" 같은 형용사만 출력하지 마시오. 반드시 **"방수파우치"**처럼 명사형 상품명을 출력하시오.
2. **범주 오류 주의:**
   - "씻기 편한 거"는 **'수세미'**가 아니라 **'실리콘용기/오픈형구조'**를 원할 확률이 높음.
   - "이동 중 안 섞이는 거"는 **'밀폐용기'**가 아니라 **'칸막이함'**임.

# [Few-Shot Examples]
User: "화장실 바닥이 자꾸 미끄러워서 위험해."
Pattern: [2. 안전/보호형] - 미끄러짐 방지
Keyword: 미끄럼방지매트

User: "샴푸 통 누르기 귀찮은데 손만 대면 나오는 거 없나?"
Pattern: [3. 편의/효율성] - 힘 안 들이고 자동 토출
Keyword: 자동디스펜서

User: "여행 가는데 약들이 가방 안에서 뒤섞여서 엉망이야."
Pattern: [4. 내부 정리/분할] - 섞임 방지(칸막이)
Keyword: 약통 (또는 분할케이스)

User: "싱크대에서 냄새가 너무 올라와."
Pattern: [1. 문제 해결형] - 냄새 차단
Keyword: 배수구덮개 (또는 배수구트랩)

User: "벽지 손상 없이 달력 걸고 싶어."
Pattern: [4. 공간 정리] - 벽 손상 없는 거치
Keyword: 꼭꼬핀

    # Current Query: "{query}"

    # Output Format
    Reasoning: <Category> - <Function Analysis>
    Primary Keyword: <One Standard Keyword>
    """
    try:
        start_time = time.time()
        response = model.generate_content(prompt)
        end_time = time.time()
        latency = end_time - start_time
        
        # Parse output
        response_text = response.text.strip()
        keyword = ""
        
        # New parsing logic for "Primary Keyword:"
        for line in response_text.split('\n'):
            if "Primary Keyword:" in line:
                # Remove label and cleanup
                raw_keyword = line.split("Primary Keyword:")[1].strip()
                # Simple cleanup: remove (...) if present
                if "(" in raw_keyword:
                    raw_keyword = raw_keyword.split("(")[0].strip()
                keyword = raw_keyword
                break
        
        # Fallback if specific format not found
        if not keyword:
             # Try logical fallback or generic "Keyword:" search
             for line in response_text.split('\n'):
                if "Keyword:" in line and "Primary" not in line: # generic match
                    raw_keyword = line.split("Keyword:")[1].strip()
                    if "(" in raw_keyword:
                         raw_keyword = raw_keyword.split("(")[0].strip()
                    keyword = raw_keyword
                    break


        usage = response.usage_metadata
        prompt_tokens = usage.prompt_token_count
        candidates_tokens = usage.candidates_token_count
        total_tokens = usage.total_token_count

        return {
            "keyword": keyword,
            "latency": latency,
            "tokens": {
                "prompt": prompt_tokens,
                "completion": candidates_tokens,
                "total": total_tokens
            }
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    questions = load_questions()
    if not questions:
        return

    print(f"Loaded {len(questions)} questions.")
    print("-" * 50)
    
    output_txt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted_keywords_part_refill_questions_100.txt")
    print(f"Saving results to: {output_txt_path}")

    with open(output_txt_path, "w", encoding="utf-8") as f:
        for i, q in enumerate(questions):
            result = extract_keyword(q)
            
            if "error" in result:
                line = f"Q: {q} -> Error: {result['error']}"
            else:
                keyword = result["keyword"]
                latency = result["latency"]
                tokens = result["tokens"]
                
                # Format: Question -> Keyword (Latency: Xs, Tokens: [P:X, C:X, T:X])
                line = f"Q: {q} -> Keyword: {keyword}"
                meta_info = f"(Latency: {latency:.3f}s, Tokens: [P:{tokens['prompt']}, C:{tokens['completion']}, T:{tokens['total']}])"
                
                print(f"[{i+1}/{len(questions)}] {line} {meta_info}")
                f.write(f"{line} {meta_info}\n")
            
            f.flush() 

    print(f"\nAnalysis complete. Results saved to {output_txt_path}")

if __name__ == "__main__":
    main()
