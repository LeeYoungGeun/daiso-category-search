import json
import os
import time
from poc_v5_experiment_phase_1 import advanced_rerank

# Configuration
TEST_CASES_PATH = "data/poc_v5_golden_test_cases.json"
PRODUCT_DB_PATH = "data/poc_v5_mock_product_db.json"
REPORT_PATH = "document/poc_v5_experiment_resalts_phase_1.md"

def load_products():
    with open(PRODUCT_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_test_cases():
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def run_evaluation():
    print("🚀 Starting PoC v5 Evaluation...")
    
    # Load Data
    products = load_products()
    product_map = {str(p['id']): p for p in products} # ID mapping
    test_cases = load_test_cases()
    
    total = len(test_cases)
    correct = 0
    results = []
    
    start_time_all = time.time()

    for i, case in enumerate(test_cases):
        case_id = case['id']
        query = case['query']
        scenario = case['scenario_type']
        
        # 1. Prepare Candidates (Simulation)
        final_candidates = []
        gt_ids = [str(gid) for gid in case.get('ground_truth_ids_hint', [])]
        
        # Helper: Find product by ID with fallback name
        def get_product_by_id(pid, hint_fallback=None):
            if pid in product_map:
                return product_map[pid]
            # Improved Fallback: Use the hint name if available
            name = hint_fallback if hint_fallback else f"Target Product {pid}"
            desc = f"Simulated product description for {name}"
            return {"id": pid, "name": name, "desc": desc}

        # Helper: Find ID by Name hint (heuristic)
        def find_product_by_hint_name(hint):
            for pid, pdata in product_map.items():
                if hint in pdata['name']:
                    return pdata
            return None

        # [Step A] Explicitly Inject Ground Truth items first
        existing_ids = set()
        
        # Mapping: hint_string -> is_covered
        # We assume strict 1:1 mapping by index for the first N hints where N = len(gt_ids)
        covered_hints = set()

        for idx, gid in enumerate(gt_ids):
            # Try to align with a hint
            aligned_hint = None
            if idx < len(case['candidates_hint']):
                aligned_hint = case['candidates_hint'][idx]
                covered_hints.add(aligned_hint)
            
            # Fetch GT Item
            # Force Overwrite: The Test Case defines the "Truth" for this scenario.
            # Even if DB has ID 301 as "Tupperware", if the Test Case implies it's "Insulation Sheet",
            # we must present it as "Insulation Sheet" to the LLM to validate reasoning.
            gt_item = get_product_by_id(gid)
            
            if aligned_hint:
                # Force update name/desc to match the hint
                gt_item = gt_item.copy() # Don't mutate global cache unique check
                gt_item['name'] = aligned_hint
                gt_item['desc'] = f"Simulated product description for {aligned_hint}"
            
            final_candidates.append(gt_item)
            existing_ids.add(str(gt_item['id']))

        # [Step B] Add Distractors/Hints
        for hint in case['candidates_hint']:
            # If this hint was already used to map a GT, skip it
            if hint in covered_hints:
                continue
                
            # Extra Check: Fuzzy coverage (for unmapped hints that might still overlap)
            # e.g. if GT list has 1 item, but Hints have 2 items describing it? (Rare)
            hint_clean = hint.replace(" ", "").lower()
            is_covered_fuzzy = False
            for c in final_candidates:
                c_name_clean = c['name'].replace(" ", "").lower()
                if hint_clean in c_name_clean or c_name_clean in hint_clean:
                    is_covered_fuzzy = True
                    break
            
            if is_covered_fuzzy:
                continue
            
            # If not covered, try to find a real product in DB matching this hint
            real_product = find_product_by_hint_name(hint)
            if real_product:
                 if str(real_product['id']) not in existing_ids:
                     final_candidates.append(real_product)
                     existing_ids.add(str(real_product['id']))
            else:
                 # Create Noise
                 mock_item = {
                    "id": f"NOISE_{abs(hash(hint))}", 
                    "name": hint, 
                    "desc": f"Description for {hint}"
                 }
                 final_candidates.append(mock_item)
                 
        # Shuffle
        import random
        random.shuffle(final_candidates)
        
        # 2. Run Reranker
        print(f"[{i+1}/{total}] Query: {query} ({scenario})...", end="", flush=True)
        result = advanced_rerank(query, final_candidates)
        
        prediction = str(result.get('selected_id')) if result.get('selected_id') else None
        reason = result.get('reason')
        
        # 3. Grade
        # Pass if:
        # A) Prediction is in GT IDs
        # B) GT is empty (expecting None) AND Prediction is None
        
        is_pass = False
        if not gt_ids and prediction is None:
            is_pass = True
        elif prediction in gt_ids:
            is_pass = True
            
        if is_pass:
            correct += 1
            print(" ✅ PASS")
        else:
            print(f" ❌ FAIL (Pred: {prediction}, GT: {gt_ids})")

        # DEBUG: Print Candidates for Case 02, 10, etc.
        if i < 20: 
            print(f"\n[DEBUG TC_{i+1}] Query: {query}")
            print(f"  GT IDs: {gt_ids}")
            print(f"  Covered Hints: {covered_hints}")
            for c in final_candidates:
                print(f"    - [{c['id']}] {c['name']}")
            
        results.append({
            "id": case_id,
            "query": query,
            "scenario": scenario,
            "prediction": prediction,
            "ground_truth": gt_ids,
            "is_pass": is_pass,
            "reason": reason,
            "candidates_preview": [c['name'] for c in final_candidates]
        })
        
        # Rate limit prevention
        time.sleep(0.5)

    duration = time.time() - start_time_all
    accuracy = (correct / total) * 100
    
    print("-" * 60)
    print(f"🏁 Evaluation Complete in {duration:.2f}s")
    print(f"📊 Accuracy: {correct}/{total} ({accuracy:.1f}%)")
    
    # Save Report
    generate_report(results, accuracy)

def generate_report(results, accuracy):
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# PoC v5 Final Evaluation Report\n\n")
        f.write(f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **Accuracy**: **{accuracy:.1f}%**\n")
        f.write(f"- **Total Cases**: {len(results)}\n\n")
        
        f.write("## 1. Summary of Failures\n")
        failures = [r for r in results if not r['is_pass']]
        if not failures:
            f.write("🎉 **Perfect Score! No failures.**\n")
        else:
            f.write("| ID | Query | Scenario | Prediction | GT | Reason |\n")
            f.write("|:---|:---|:---|:---|:---|:---|\n")
            for fail in failures:
                f.write(f"| {fail['id']} | {fail['query']} | {fail['scenario']} | {fail['prediction']} | {fail['ground_truth']} | {fail['reason']} |\n")
        
        f.write("\n## 2. Detailed Results\n")
        f.write("| ID | Query | Scenario | Result | LLM Reasoning |\n")
        f.write("|:---|:---|:---|:---|:---|\n")
        for r in results:
            icon = "🟢" if r['is_pass'] else "🔴"
            f.write(f"| {r['id']} | {r['query']} | {r['scenario']} | {icon} | {r['reason']} |\n")
            
    print(f"📄 Report saved to {REPORT_PATH}")

if __name__ == "__main__":
    run_evaluation()
