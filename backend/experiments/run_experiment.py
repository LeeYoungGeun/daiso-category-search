import asyncio
import sys
import os

# Add parent directory to path to import backend modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.logic.nlu import analyze_text, generate_tail_question

test_cases = [
    "다이소에서 파는 3000원짜리 수납장 있어?",
    "파란색 볼펜 찾아줘",
    "이거 배송 언제 돼?",
    "안녕",
    "캠핑용품 뭐 있어?", # Ambiguous
    "드릴" # Ambiguous
]

async def run_experiments():
    print(f"{'Input Text':<30} | {'Intent':<10} | {'Need Clarification':<20} | {'Tail Question'}")
    print("-" * 100)
    
    for text in test_cases:
        try:
            result = await analyze_text(text)
            tail_q = ""
            if result.needs_clarification:
                tail_q = await generate_tail_question(text, result.slots.model_dump())
            
            print(f"{text:<30} | {result.intent.value:<10} | {str(result.needs_clarification):<20} | {tail_q}")
        except Exception as e:
            print(f"Error processing '{text}': {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_experiments())
