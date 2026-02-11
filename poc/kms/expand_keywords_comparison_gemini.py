
import os
import re
import time
import json
import asyncio
from typing import List, Dict, Any
from dotenv import load_dotenv
import sys

# Import Gemini logic from existing nlu.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.logic.nlu import expand_search_keywords as expand_gemini_func

load_dotenv()

COMPARISON_REPORT_PATH = r"c:\Users\301\dev\daiso-category-search-kms\backend\logic\extracted_keywords_1question.txt"
OUTPUT_REPORT_PATH = r"c:\Users\301\dev\daiso-category-search-kms\backend\logic\expansion_result_gemini_1question.json"

def parse_comparison_report(file_path: str) -> List[str]:
    keywords = set()
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return []
        
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line in lines:
        # Expected format example: 
        # Q: ... -> Keyword: 청소집게 (Gemini ...
        match = re.search(r'Keyword:\s*([^(]+)\s*\(', line)
        if match:
            kw = match.group(1).strip()
            keywords.add(kw)
            
    return list(keywords)

async def main():
    script_start_time = time.time()
    print(f"Reading matched keywords from {COMPARISON_REPORT_PATH}...")
    keywords = parse_comparison_report(COMPARISON_REPORT_PATH)
    print(f"Found {len(keywords)} unique keywords.")
    
    results = []
    api_latencies = []
    processing_times = []
    
    # Process all keywords
    for i, kw in enumerate(keywords):
        func_start_time = time.time()
        
        # Call Gemini expansion (using existing nlu logic)
        try:
             # usage now contains 'latency_seconds' from nlu.py modification
             expanded_list, usage = await expand_gemini_func(kw, return_usage=True)
             
             func_end_time = time.time()
             total_time = func_end_time - func_start_time # Total time including wrapper overhead
             
             api_time = usage.get("latency_seconds", total_time) # Fallback to total if not found
             processing_time = total_time - api_time
             if processing_time < 0: processing_time = 0

             api_latencies.append(api_time)
             processing_times.append(processing_time)
             
             # Log immediately
             print(f"[Gemini] {i+1}/{len(keywords)}: '{kw}' -> {len(expanded_list)} items")
             print(f"    ↳ API Call: {api_time:.3f}s | Processing/Overhead: {processing_time:.3f}s")
             
             results.append({
                 "keyword": kw,
                 "expanded": expanded_list,
                 "total_time_seconds": total_time,
                 "api_latency_seconds": api_time,
                 "processing_overhead_seconds": processing_time,
                 "total_tokens": usage.get("total_tokens", 0),
                 "prompt_tokens": usage.get("prompt_tokens", 0),
                 "completion_tokens": usage.get("completion_tokens", 0)
             })

        except Exception as e:
            print(f"Error processing {kw}: {e}")
            results.append({"keyword": kw, "error": str(e)})

    # Save
    with open(OUTPUT_REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    script_end_time = time.time()
    total_duration = script_end_time - script_start_time

    # Summary Statistics
    valid_count = len(api_latencies)
    if valid_count > 0:
        # API Stats
        max_api = max(api_latencies)
        min_api = min(api_latencies)
        avg_api = sum(api_latencies) / valid_count
        
        # Processing Stats
        max_proc = max(processing_times)
        min_proc = min(processing_times)
        avg_proc = sum(processing_times) / valid_count
        
        stats_msg = (
            f"\n[Gemini Expansion Analysis (N={valid_count})]\n"
            f"1. API Call Latency (Network + Model):\n"
            f"   - AVG: {avg_api:.3f}s (Min: {min_api:.3f}s, Max: {max_api:.3f}s)\n"
            f"2. Processing/Overhead Time (Script Logic):\n"
            f"   - AVG: {avg_proc:.3f}s (Min: {min_proc:.3f}s, Max: {max_proc:.3f}s)\n"
        )
    else:
        stats_msg = "\n[Gemini Stats] No successful requests."

    print(stats_msg)
    print(f"Total Script Execution Time: {total_duration:.2f} seconds")
    print(f"Results saved to {OUTPUT_REPORT_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
