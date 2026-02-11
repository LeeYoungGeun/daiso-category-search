"""
Category Matcher - Match products to Daiso categories
Based on keyword matching from product names
"""
import sqlite3
import os
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), 'products.db')

# Daiso category structure (대분류 > 중분류 > keywords)
CATEGORIES = {
    "뷰티/위생": {
        "스킨케어": ["스킨", "로션", "크림", "에센스", "세럼", "토너", "마스크팩", "팩", "패치"],
        "화장지/물티슈": ["화장지", "휴지", "물티슈", "티슈", "롤화장지", "템포"],
        "메이크업": ["립스틱", "립", "아이라이너", "마스카라", "파운데이션", "쿠션", "블러셔", "아이섀도우"],
        "네일용품": ["네일", "매니큐어", "제거제", "네일팁"],
        "미용소품": ["거울", "빗", "머리끈", "헤어밴드", "고무줄", "헤어핀"],
        "맨케어": ["면도기", "쉐이빙", "남성"],
        "헤어/바디": ["샴푸", "린스", "바디워시", "치약", "칫솔", "세정제", "손세정"],
    },
    "주방용품": {
        "식기/그릇": ["그릇", "접시", "공기", "대접", "면기", "찬기", "밥그릇"],
        "잔/컵/물병": ["컵", "머그", "텀블러", "물병", "유리컵", "종이컵"],
        "밀폐/보관용기": ["밀폐용기", "보관용기", "저장용기", "도시락", "반찬통", "김치통"],
        "수저/커트러리": ["수저", "숟가락", "젓가락", "포크", "나이프"],
        "주방잡화": ["주방장갑", "행주", "수세미", "설거지", "세제", "앞치마"],
        "조리도구": ["국자", "뒤집개", "집게", "칼", "도마", "가위", "주걱"],
        "팬/냄비": ["냄비", "프라이팬", "뚝배기", "주전자"],
        "일회용품": ["일회용", "종이접시", "나무젓가락", "빨대", "위생장갑"],
    },
    "청소/욕실": {
        "욕실용품": ["비누", "비누케이스", "샤워볼", "수건", "욕실매트", "규조토", "칫솔걸이"],
        "청소도구": ["청소", "빗자루", "쓰레받기", "밀대", "걸레", "브러쉬", "청소솔", "솔"],
        "세탁용품": ["세탁", "빨래", "세탁망", "옷걸이", "빨래집게", "건조대"],
        "방향/탈취": ["방향제", "탈취제", "향초", "디퓨저"],
    },
    "수납/정리": {
        "수납함": ["수납함", "정리함", "서랍장", "바구니", "수납박스", "옷정리"],
        "옷걸이/행거": ["옷걸이", "행거", "바지걸이"],
        "정리용품": ["정리", "파일", "케이블정리", "정리대"],
        "진공백": ["진공", "압축팩", "이불압축"],
    },
    "문구/팬시": {
        "필기구": ["볼펜", "연필", "샤프", "형광펜", "사인펜", "마카", "필기구"],
        "노트/메모": ["노트", "메모지", "포스트잇", "스티커", "다이어리"],
        "사무용품": ["파일", "클립", "스테이플러", "가위", "테이프", "풀"],
        "학용품": ["색연필", "크레파스", "물감", "자"],
    },
    "인테리어/원예": {
        "인테리어소품": ["액자", "사진", "장식", "조화", "화분", "인형"],
        "원예용품": ["화분", "흙", "씨앗", "원예", "화분받침"],
        "조명": ["조명", "스탠드", "무드등", "전구", "LED"],
    },
    "공구/디지털": {
        "공구": ["공구", "드라이버", "펜치", "망치", "줄자", "테이프"],
        "전기용품": ["멀티탭", "연장선", "충전기", "케이블", "어댑터", "USB"],
        "건전지": ["건전지", "배터리", "AAA", "AA"],
    },
    "식품": {
        "과자/스낵": ["과자", "스낵", "칩", "쿠키", "초콜릿", "젤리", "캔디"],
        "음료": ["음료", "주스", "커피", "차", "물"],
        "조미료": ["소금", "설탕", "간장", "참기름", "조미료"],
    },
    "스포츠/레저/취미": {
        "운동용품": ["운동", "요가", "덤벨", "스트레칭", "헬스"],
        "캠핑/레저": ["캠핑", "텐트", "랜턴", "돗자리", "쿨러백"],
        "자동차용품": ["자동차", "차량", "방향제"],
    },
    "패션/잡화": {
        "양말/스타킹": ["양말", "스타킹", "덧신"],
        "슬리퍼": ["슬리퍼", "실내화"],
        "가방/파우치": ["가방", "파우치", "에코백", "장바구니"],
        "우산/장갑": ["우산", "장갑", "목도리", "모자"],
    },
    "반려동물": {
        "강아지용품": ["강아지", "애견", "개"],
        "고양이용품": ["고양이", "캣"],
        "반려동물공통": ["사료", "간식", "배변패드", "펫"],
    },
    "유아/완구": {
        "완구": ["장난감", "인형", "블록", "레고", "완구"],
        "유아용품": ["유아", "아기", "젖병", "기저귀"],
    },
}

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_category_tables():
    """Create category related tables"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Categories lookup table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            major TEXT NOT NULL,
            middle TEXT NOT NULL,
            UNIQUE(major, middle)
        )
    ''')
    
    # Add category columns to products table if not exists
    try:
        cursor.execute('ALTER TABLE products ADD COLUMN category_major TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE products ADD COLUMN category_middle TEXT')
    except:
        pass
    
    conn.commit()
    conn.close()
    print("[OK] Category tables initialized")

def populate_categories():
    """Insert categories into lookup table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    count = 0
    for major, middles in CATEGORIES.items():
        for middle in middles.keys():
            cursor.execute('''
                INSERT OR IGNORE INTO categories (major, middle) VALUES (?, ?)
            ''', (major, middle))
            count += 1
    
    conn.commit()
    conn.close()
    print(f"[OK] Inserted {count} category entries")

def match_product_to_category(product_name: str) -> tuple:
    """Match product name to category using keywords"""
    product_lower = product_name.lower()
    
    for major, middles in CATEGORIES.items():
        for middle, keywords in middles.items():
            for keyword in keywords:
                if keyword in product_lower:
                    return (major, middle)
    
    return ("기타", "미분류")

def update_all_products():
    """Match all products to categories"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, name FROM products')
    products = cursor.fetchall()
    
    print(f"Matching {len(products)} products to categories...")
    
    matched = 0
    unmatched = 0
    
    for product in products:
        product_id = product['id']
        name = product['name']
        
        major, middle = match_product_to_category(name)
        
        cursor.execute('''
            UPDATE products SET category_major = ?, category_middle = ? WHERE id = ?
        ''', (major, middle, product_id))
        
        if major != "기타":
            matched += 1
        else:
            unmatched += 1
    
    conn.commit()
    conn.close()
    
    print(f"\nResults:")
    print(f"   Matched: {matched}")
    print(f"   Unmatched: {unmatched}")

def get_drill_down_context(products: list) -> str:
    """
    Generate the Drill-Down context string for the LLM.
    Groups products by Major > Middle category.
    """
    if not products:
        return "관련 상품 없음"

    grouped = defaultdict(lambda: defaultdict(list))
    
    for p in products:
        # Check if product dict already has 'category_major' populated
        # If not, try to match it on the fly (robustness)
        major = p.get('category_major')
        middle = p.get('category_middle')
        
        if not major or not middle:
            major, middle = match_product_to_category(p['name'])
        
        grouped[major][middle].append(p['name'])

    # Format output
    lines = []
    
    # Sort by major category with most items
    sorted_majors = sorted(grouped.items(), key=lambda x: sum(len(v) for v in x[1].values()), reverse=True)
    
    for major, middles in sorted_majors[:3]: # Top 3 Majors
        lines.append(f"[{major}]")
        for middle, items in list(middles.items())[:3]: # Top 3 Middles per Major
            items_str = ", ".join(items[:3])
            lines.append(f"  - {middle}: {items_str}")
            
    context = "\n".join(lines)
    if not context:
        context = "관련 상품 없음"
        
    return context

if __name__ == "__main__":
    print("=" * 50)
    print("[Category Matcher]")
    print("=" * 50)
    
    init_category_tables()
    populate_categories()
    update_all_products()
