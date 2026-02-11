"""
Test script for integrated search pipeline
Tests the /v1/search endpoint
"""

import asyncio
import sys
import os
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Check for API key
if not os.getenv("GEMINI_API_KEY"):
    print("ERROR: GEMINI_API_KEY not found in environment variables")
    print("Please create a .env file with: GEMINI_API_KEY=your_key_here")
    sys.exit(1)

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from backend.logic.integrated_search import get_pipeline


async def test_search():
    """Test the integrated search pipeline"""
    
    pipeline = get_pipeline()
    
    # Test cases
    test_queries = [
        "욕실 매트 어디 있어요?",
        "건전지 찾아줘",
        "화장지",
        "안녕하세요",  # Out of scope
    ]
    
    print("=" * 80)
    print("Integrated Search Pipeline Test")
    print("=" * 80)
    
    for idx, query in enumerate(test_queries, 1):
        print(f"\n[Test {idx}] Query: '{query}'")
        print("-" * 80)
        
        try:
            result = await pipeline.search(query=query)
            
            print(f"[OK] Request ID: {result['request_id']}")
            print(f"[OK] Intent: {result['intent']}")
            print(f"[OK] In Scope: {result['is_in_scope']}")
            
            if result['is_in_scope']:
                print(f"[OK] Found {len(result['top3'])} products")
                
                for i, product in enumerate(result['top3'], 1):
                    print(f"  {i}. {product['name']} ({product['price']}원)")
                    print(f"     Category: {product['category_major']} > {product['category_middle']}")
                    print(f"     Top1: {product['is_top1']}")
                
                if result.get('top1_handover'):
                    print(f"[OK] QR Handover: {result['top1_handover']['qr_payload']}")
            else:
                print(f"[SKIP] Out of scope: {result.get('message', 'N/A')}")
            
            # Timing
            timing = result['timing_ms']
            print(f"\n[TIME] Performance:")
            print(f"  - NLU: {timing.get('nlu', 0)}ms")
            print(f"  - Expand: {timing.get('expand', 0)}ms")
            print(f"  - Search: {timing.get('search', 0)}ms")
            print(f"  - Rerank: {timing.get('rerank', 0)}ms")
            print(f"  - Location: {timing.get('location', 0)}ms")
            print(f"  - Total: {timing.get('total', 0)}ms")
            
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("Test completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_search())
