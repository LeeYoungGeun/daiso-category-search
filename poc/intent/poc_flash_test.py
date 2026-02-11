import os
import csv
import time
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()
API_KEY = os.environ.get("GOOGLE_API_KEY")

if not API_KEY:
    print("Error: GOOGLE_API_KEY environment variable is not set.")
    exit(1)

genai.configure(api_key=API_KEY)

MODEL_NAME = "gemini-2.0-flash"

generation_config = {
    "temperature": 0.0,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 5,
}

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

system_prompt = """
너는 다이소 매장의 태블릿에 탑재된 AI 점원이다.
사용자의 발화를 분석하여, 매장 직원의 응대가 필요한지(Y), 필요 없는지(N) 판단하여 알파벳 한 글자만 출력하라.

[판단 기준]
1. Y (응대 필요):
   - 다이소 상품 찾기, 재고 확인, 상품 추천 요청
   - 매장 시설(화장실, 엘리베이터, 주차장) 및 운영 시간 문의
   - 결제, 영수증 재발급, 봉투 구매, 멤버십 포인트 적립 문의
   - 생활 속 문제 해결을 위한 상품 탐색 (예: "욕실이 미끄러워")

2. N (응대 불필요/무시):
   - 다이소와 무관한 사적인 잡담 (인사, 농담, MBTI, 연애 상담)
   - 외부 정보 질문 (날씨, 주식, 비트코인, 뉴스, 연예인)
   - 타 브랜드(맥도날드, 스타벅스, 편의점) 관련 질문
   - 단순한 불만 토로, 욕설, 의미 없는 혼잣말

[Few-Shot 예시]
User: "건전지 어디 있어?" -> Model: Y
User: "포인트 적립 되나요?" -> Model: Y
User: "화장실 비번 뭐야?" -> Model: Y
User: "비트코인 얼마야?" -> Model: N
User: "맥도날드 가격 알려줘" -> Model: N
User: "나랑 결혼할래?" -> Model: N
User: "사랑해" -> Model: N
"""

try:
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=generation_config,
        system_instruction=system_prompt
    )
except Exception as e:
    print(f"Error initializing model '{MODEL_NAME}': {e}")
    exit(1)

INPUT_FILE = 'daiso_poc_data.csv'

def process_csv():
    print(f"Reading {INPUT_FILE}...")

    # [수정] 헤더와 데이터 로딩 방식 안전하게 변경
    data_rows = []
    header = []

    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader) # 첫 줄(헤더) 읽기
            data_rows = list(reader) # 나머지 데이터 읽기
    except FileNotFoundError:
        print(f"Error: File {INPUT_FILE} not found.")
        return

    try:
        idx_utterance = header.index('사용자 발화 (Utterance)')
        idx_gt = header.index('[GT] 정답')
        idx_pred = header.index('[M1] Flash 예측')
        idx_speed = header.index('[M1] 속도(ms)')
        idx_judge = header.index('[M1] 판정')
    except ValueError as e:
        print(f"Error: CSV Header mismatch. {e}")
        return

    total_count = len(data_rows)
    print(f"Total rows: {total_count}")
    print(f"Model: {MODEL_NAME} (Billing Enabled Mode)")

    delay_sec = 0.5
    print(f"Speed Limit: Waiting {delay_sec}s between requests...")

    correct_count = 0

    for i, row in enumerate(data_rows):
        utterance = row[idx_utterance]
        gt = row[idx_gt].strip().upper()

        if not utterance:
            continue

        print(f"[{i+1}/{total_count}] Processing: {utterance}", end="... ", flush=True)

        start_time = time.time()
        prediction = "ERROR"
        judge = "Error"

        try:
            response = model.generate_content(utterance, safety_settings=safety_settings)
            raw_text = response.text.strip().upper()

            if 'Y' in raw_text:
                prediction = 'Y'
            elif 'N' in raw_text:
                prediction = 'N'
            else:
                prediction = raw_text

            if prediction == gt:
                judge = 'O'
                correct_count += 1
            else:
                judge = 'X'

        except Exception as e:
            print(f"\n  Error: {e}")
            prediction = "ERROR"

        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)

        row[idx_pred] = prediction
        row[idx_speed] = str(duration_ms)
        row[idx_judge] = judge

        print(f"Pred: {prediction}, GT: {gt}, Time: {duration_ms}ms ({judge})")

        # [핵심 수정] 저장할 때 헤더와 데이터(data_rows)를 모두 씁니다.
        if (i + 1) % 10 == 0:
            with open(INPUT_FILE, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)   # 헤더 쓰고
                writer.writerows(data_rows) # 데이터 씁니다

        time.sleep(delay_sec)

    # 최종 저장
    with open(INPUT_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data_rows)

    accuracy = (correct_count / total_count) * 100 if total_count > 0 else 0
    print(f"\nDone! Accuracy: {accuracy:.2f}%")

if __name__ == "__main__":
    process_csv()