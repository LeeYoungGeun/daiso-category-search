
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def test_connect():
    print("Testing Gemini Connection...")
    api_key = os.getenv("GEMINI_API_KEY")
    print(f"API Key present: {bool(api_key)}")
    if api_key:
        print(f"API Key start: {api_key[:5]}...")
    
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
        print("Client initialized. Listing models...")
        # Simple generation test
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents="Hello"
        )
        print(f"Response: {response.text}")
        print("Success!")
        
    except ImportError:
        print("Error: google-genai package not installed.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_connect())
