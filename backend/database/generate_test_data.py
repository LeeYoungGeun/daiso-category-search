"""
Test Utterance Generator
Generates 3000 utterances (85% normal, 15% hard)
"""
import random
from database import get_connection, get_all_products, get_utterance_count

TARGET_TOTAL = 3000
NORMAL_RATIO = 0.85
HARD_RATIO = 0.15

NORMAL_TEMPLATES = [
    "{name} 있나요?", "{name} 어디 있어요?", "{name} 찾고 있어요",
    "{name} 어디서 파나요?", "{name} 재고 있나요?", "{name} 위치 알려주세요",
    "{name} 어느 코너에 있어요?", "혹시 {name} 있나요?", "{name} 팔아요?",
    "{name} 코너가 어디예요?", "{name} 가격이 얼마예요?", "{name}요",
    "{name} 주세요", "{name} 보여주세요",
]

HARD_TEMPLATES = [
    "{name} 어딨어요?", "{name} 그거 있잖여", "{name} 있능가?",
    "{name} 어데 있노?", "{name} 있나 안있나?", "{name} 그거 어딨능교?",
    "{name} 있슈?", "{name} 어딨슈?", "{name} 그거 있나유?",
    "저기요, {name}", "그거... {name} 같은 거", "{name}!",
    "{name} 비슷한 거", "{name} 같은 거 찾는데요",
]

PRODUCT_VARIATIONS = {
    "물티슈": ["물티슈", "젖은 티슈", "물휴지"],
    "휴지": ["휴지", "화장지", "두루마리"],
    "건전지": ["건전지", "배터리", "밧데리"],
}

def get_product_variation(name: str) -> str:
    for key, variations in PRODUCT_VARIATIONS.items():
        if key in name:
            return random.choice(variations)
    return name

def insert_utterance(utterance: str, difficulty: str, product_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO test_utterances (utterance, difficulty, expected_product_id)
            VALUES (?, ?, ?)
        ''', (utterance, difficulty, product_id))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def generate_utterances():
    print("=" * 50)
    print("🚀 Generating Test Utterances")
    print(f"🎯 Target: {TARGET_TOTAL}")
    print("=" * 50)
    
    products = get_all_products()
    if not products:
        print("❌ No products. Run crawler first.")
        return
    
    if get_utterance_count() >= TARGET_TOTAL:
        print(f"✅ Already have {get_utterance_count()} utterances.")
        return
    
    normal_target = int(TARGET_TOTAL * NORMAL_RATIO)
    hard_target = int(TARGET_TOTAL * HARD_RATIO)
    normal_count, hard_count = 0, 0
    
    print("\n📝 Generating normal...")
    while normal_count < normal_target:
        product = random.choice(products)
        template = random.choice(NORMAL_TEMPLATES)
        name = get_product_variation(product['name']) if random.random() > 0.7 else product['name']
        if insert_utterance(template.format(name=name), 'normal', product['id']):
            normal_count += 1
            if normal_count % 500 == 0:
                print(f"   Normal: {normal_count}/{normal_target}")
    
    print("\n📝 Generating hard...")
    while hard_count < hard_target:
        product = random.choice(products)
        template = random.choice(HARD_TEMPLATES)
        name = product['name'].split()[0] if len(product['name'].split()) > 1 else product['name']
        if insert_utterance(template.format(name=name), 'hard', product['id']):
            hard_count += 1
            if hard_count % 100 == 0:
                print(f"   Hard: {hard_count}/{hard_target}")
    
    print(f"\n✅ Generated {get_utterance_count()} utterances!")

if __name__ == "__main__":
    generate_utterances()
