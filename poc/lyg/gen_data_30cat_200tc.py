# gen_data_30cat_200tc.py
from __future__ import annotations
from pathlib import Path
import random

random.seed(7)

OUT_CATALOG = Path("catalog.30cat.tsv")
OUT_TESTCASES = Path("testcases.200.tsv")

# 30 categories (요청 반영)
CATS = [
    "bathroom_mat","yoga_mat","entry_mat","kitchen_mat","car_mat",
    "towel","slipper","shower_curtain","cleaning_glove","dish_sponge",
    "trash_bag","air_freshener","humidifier","vacuum","air_purifier",
    "face_mask","shampoo","conditioner","body_wash","toothpaste",
    "toothbrush","laundry_detergent","fabric_softener","water_filter","coffee_capsule",
    "tea_bag","snack_bar","protein_powder","phone_case","charger",
]

KR = {
    "bathroom_mat":"욕실 매트","yoga_mat":"요가 매트","entry_mat":"현관 매트","kitchen_mat":"주방 매트","car_mat":"차량 매트",
    "towel":"수건","slipper":"슬리퍼","shower_curtain":"샤워커튼","cleaning_glove":"청소장갑","dish_sponge":"수세미",
    "trash_bag":"쓰레기봉투","air_freshener":"방향제","humidifier":"가습기","vacuum":"청소기","air_purifier":"공기청정기",
    "face_mask":"마스크","shampoo":"샴푸","conditioner":"린스","body_wash":"바디워시","toothpaste":"치약",
    "toothbrush":"칫솔","laundry_detergent":"세탁세제","fabric_softener":"섬유유연제","water_filter":"정수필터","coffee_capsule":"커피캡슐",
    "tea_bag":"티백","snack_bar":"스낵바","protein_powder":"단백질 파우더","phone_case":"휴대폰 케이스","charger":"충전기",
}

# 카테고리별 “목적/설명형”에 쓰일 특징 키워드(혼동/현실성용)
FEATURES = {
    "bathroom_mat":["미끄럼방지","물빠짐","흡수","규조토","건조"],
    "yoga_mat":["6mm","10mm","쿠션","필라테스","미끄럼방지"],
    "entry_mat":["먼지제거","현관","발매트","논슬립","털빠짐"],
    "kitchen_mat":["발피로","방수","기름튐","주방","쿠션"],
    "car_mat":["차량","발매트","방수","트렁크","3D"],
    "towel":["면100","흡수","호텔","대형","세트"],
    "slipper":["미끄럼방지","실내","욕실용","EVA","쿠션"],
    "shower_curtain":["방수","곰팡이방지","샤워","커튼링","폴리에스터"],
    "cleaning_glove":["고무","기모","긴팔","설거지","내구성"],
    "dish_sponge":["항균","세척력","수세미","거품","스크래치방지"],
    "trash_bag":["대형","분리수거","튼튼","냄새차단","롤"],
    "air_freshener":["탈취","향","디퓨저","차량용","리필"],
    "humidifier":["초음파","가열","대용량","무드등","저소음"],
    "vacuum":["무선","흡입력","헤파필터","스틱","로봇"],
    "air_purifier":["헤파","필터","미세먼지","CADR","저소음"],
    "face_mask":["KF94","덴탈","대형","숨쉬기편함","귀편함"],
    "shampoo":["두피","비듬","탈모","약산성","향"],
    "conditioner":["손상모","윤기","엉킴","단백질","향"],
    "body_wash":["보습","향","약산성","민감피부","거품"],
    "toothpaste":["미백","구취","불소","시린이","잇몸"],
    "toothbrush":["초미세모","전동","어린이","교체모","부드러움"],
    "laundry_detergent":["액체","캡슐","드럼","얼룩","향"],
    "fabric_softener":["향","정전기","보송","리필","민감피부"],
    "water_filter":["정수","필터","교체","활성탄","호환"],
    "coffee_capsule":["네스프레소","호환","강도","디카페인","원두"],
    "tea_bag":["홍차","녹차","허브","무카페인","향"],
    "snack_bar":["저당","고단백","간식","식사대용","견과"],
    "protein_powder":["유청","WPI","초코","무맛","근육"],
    "phone_case":["투명","범퍼","맥세이프","가죽","하드"],
    "charger":["PD","고속","멀티포트","C타입","GaN"],
}

ADJ = ["프리미엄","베이직","컴팩트","대용량","저자극","초강력","저소음","휴대용","항균","고급형"]

def make_docs(docs_per_cat: int = 10):
    docs = []
    base_id = 10000
    i = 0
    for cat in CATS:
        for n in range(1, docs_per_cat + 1):
            i += 1
            doc_id = f"P-{base_id + i:05d}"
            name = KR[cat]
            feat = random.sample(FEATURES.get(cat, []), k=min(2, len(FEATURES.get(cat, [])))) if FEATURES.get(cat) else []
            title = f"{ADJ[(i + n) % len(ADJ)]} {name} {n}"
            text = f"{name} 상품. " + (" / ".join(feat) + " 특징. " if feat else "") + "실사용 목적에 맞춘 구성."
            docs.append((doc_id, title, text, cat))
    return docs

def pick_synonym(cat: str, name: str):
    # 간단한 축약/동의어 변형 (의도적으로 spelling/축약 섞음)
    variants = {
        "bathroom_mat":[f"{name}", "욕실매트", "규조토매트", "미끄럼방지매트"],
        "yoga_mat":[f"{name}", "요가매트", "필라테스매트", "운동매트"],
        "entry_mat":[f"{name}", "현관매트", "발매트", "먼지매트"],
        "kitchen_mat":[f"{name}", "주방발매트", "싱크대매트", "쿠션매트(주방)"],
        "car_mat":[f"{name}", "차매트", "차량발매트", "자동차매트"],
        "charger":[f"{name}", "고속충전기", "PD충전기", "C타입충전기"],
    }
    if cat in variants:
        return random.choice(variants[cat])
    # default: 핵심 단어만
    core = name.replace(" ", "")
    return random.choice([name, core, f"{core} 추천", f"{name} 있어요?"])

def make_testcases(docs, n_total=200):
    # 분포: exact 50 / synonym 50 / purpose 50 / noise 20 / confusion 30 = 200
    plan = [("exact",50),("synonym",50),("purpose",50),("noise",20),("confusion",30)]
    # 카테고리별 대표 문서 샘플링
    by_cat = {}
    for d in docs:
        by_cat.setdefault(d[3], []).append(d)

    tcs = []
    tc_id = 0

    def add_case(raw, intent, exp_id, exp_cat, needs, tag):
        nonlocal tc_id
        tc_id += 1
        tcs.append((
            f"TC-{tc_id:03d}",
            raw,
            intent,
            exp_id,
            exp_cat,
            "true" if needs else "false",
            f"tag={tag}"
        ))

    # exact/synonym/purpose는 특정 doc을 정답으로 설정
    for tag, cnt in plan:
        for _ in range(cnt):
            if tag in ("exact","synonym","purpose","confusion"):
                cat = random.choice(CATS)
                doc = random.choice(by_cat[cat])
                doc_id, title, text, cat = doc
                name = KR[cat]
            if tag == "exact":
                raw = f"{name} 있어요?"
                intent = name
                add_case(raw, intent, doc_id, cat, False, "exact")
            elif tag == "synonym":
                syn = pick_synonym(cat, name)
                raw = f"{syn} 추천해줘"
                intent = syn.replace("추천해줘","").strip()
                add_case(raw, intent, doc_id, cat, False, "synonym")
            elif tag == "purpose":
                feats = FEATURES.get(cat, ["좋은","추천"])
                f1 = random.choice(feats)
                raw = f"{f1} {name} 뭐가 좋아?"
                intent = f"{f1} {name}"
                add_case(raw, intent, doc_id, cat, False, "purpose")
            elif tag == "noise":
                # 평가에서 제외되도록 needs_clarification=True 권장
                raw = random.choice(["그거 있어?", "아무거나 추천", "좋은거", "어디있어", "이거 뭐임"])
                intent = raw
                add_case(raw, intent, "", "", True, "noise")
            elif tag == "confusion":
                # 의도적으로 “매트” 같이 카테고리 혼동 가능 문장 생성
                # 절반은 needs_clarification=True로 두어 스킵 유도
                ambiguous = random.random() < 0.5
                if cat.endswith("_mat"):
                    raw = "매트 추천해줘" if ambiguous else f"{name} 말고 다른 매트도 있어?"
                    intent = "매트"
                else:
                    raw = f"{name} 같은 거" if ambiguous else f"{name} 말고 비슷한 거"
                    intent = name
                add_case(raw, intent, doc_id if not ambiguous else "", cat if not ambiguous else "", ambiguous, "confusion")

    assert len(tcs) == n_total
    return tcs

def write_catalog(docs):
    lines = ["# doc_id\ttitle\ttext\tcategory"]
    for doc_id, title, text, cat in docs:
        lines.append(f"{doc_id}\t{title}\t{text}\t{cat}")
    OUT_CATALOG.write_text("\n".join(lines) + "\n", encoding="utf-8")

def write_testcases(tcs):
    header = "id\traw_text\tintent_text\texpected_doc_ids\texpected_category\tneeds_clarification\tnotes"
    lines = [header]
    for r in tcs:
        lines.append("\t".join(r))
    OUT_TESTCASES.write_text("\n".join(lines) + "\n", encoding="utf-8")

if __name__ == "__main__":
    docs = make_docs(docs_per_cat=10)  # 필요 시 20으로 올리면 600문서
    tcs = make_testcases(docs, n_total=200)
    write_catalog(docs)
    write_testcases(tcs)
    print("Wrote:", OUT_CATALOG, OUT_TESTCASES, "docs=", len(docs), "tcs=", len(tcs))
