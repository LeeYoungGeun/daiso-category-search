
import asyncio
import sys
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set UTF-8 encoding
if sys.platform == 'win32':
    import codecs
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except:
        pass

sys.path.append(str(Path(__file__).parent))

RESULT_FILE = "timing_results.txt"

def log_to_file(msg):
    with open(RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)

async def run_fallback_test():
    # Clear previous results
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write("=== Integrated Search Timing Test ===\n")
    
    log_to_file("Initializing Pipeline (Fallback Mode)...")
    
    try:
        from backend.logic import integrated_search
        
        # Mock the hybrid init to return None (forcing SQLite fallback)
        with patch('backend.logic.integrated_search._try_init_hybrid_search', return_value=None):
            pipeline = integrated_search.get_pipeline()
            
            log_to_file(f"Pipeline Mode: {pipeline.search_mode}")
            
            test_queries = ["화장지", "건전지", "파란색 볼펜"]
            
            log_to_file("\nStarting Search Test...")
            for query in test_queries:
                log_to_file(f"\nQuery: {query}")
                try:
                    t0 = time.time()
                    result = await pipeline.search(query=query)
                    total = int((time.time() - t0) * 1000)
                    
                    log_to_file(f"Results Found: {len(result['top3'])}")
                    log_to_file("Timing Breakdown:")
                    for k, v in result['timing_ms'].items():
                        log_to_file(f"  - {k}: {v}ms")
                    log_to_file(f"  - Total (measured): {total}ms")
                    
                    # Print top 1 product to verify correctness
                    if result['top3']:
                        top1 = result['top3'][0]
                        log_to_file(f"  Top Result: {top1['name']} ({top1['product_id']})")
                        
                except Exception as e:
                    log_to_file(f"Search failed: {e}")
                    import traceback
                    log_to_file(traceback.format_exc())

    except Exception as e:
        log_to_file(f"Critical Error: {e}")
        import traceback
        log_to_file(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(run_fallback_test())
