
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

# Mock Hybrid Search to force fallback or just ensure it doesn't hang
# We also need to mock NLU if Gemini is failing/hanging
# But NLU logs showed it was working earlier (just 404 on specific model).
# I'll try to let NLU run if possible, or mock it if it hangs.

async def run_fallback_test():
    print("Initializing Pipeline (Fallback Mode)...")
    
    # We need to trick IntegratedSearchPipeline to think hybrid is not available
    # We can do this by patching _try_init_hybrid_search to return None
    
    from backend.logic import integrated_search
    
    # Mock the hybrid init to return None (forcing SQLite fallback)
    with patch('backend.logic.integrated_search._try_init_hybrid_search', return_value=None):
        pipeline = integrated_search.get_pipeline()
        
        print(f"Pipeline Mode: {pipeline.search_mode}")
        
        test_queries = ["화장지", "건전지"]
        
        print("\nStarting Search Test...")
        for query in test_queries:
            print(f"\nQuery: {query}")
            try:
                # We might need to mock NLU if it requires API key and fails
                # Let's try running it first. If it fails, catch it.
                t0 = time.time()
                result = await pipeline.search(query=query)
                total = int((time.time() - t0) * 1000)
                
                print(f"Results Found: {len(result['top3'])}")
                print("Timing:")
                for k, v in result['timing_ms'].items():
                    print(f"  - {k}: {v}ms")
                print(f"  - Total (measured): {total}ms")
                
            except Exception as e:
                print(f"Search failed: {e}")
                # If NLU failed, we can't do much without mocking NLU too.

if __name__ == "__main__":
    asyncio.run(run_fallback_test())
