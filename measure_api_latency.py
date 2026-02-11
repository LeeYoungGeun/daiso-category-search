
import time
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"

def measure_nlu_latency():
    print("Measuring NLU Latency...")
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "parts": [{"text": "건전지 찾아줘"}]
        }]
    }
    
    start = time.time()
    try:
        response = requests.post(URL, headers=headers, json=data, timeout=10)
        end = time.time()
        latency = int((end - start) * 1000)
        print(f"Status: {response.status_code}")
        print(f"NLU Latency: {latency}ms")
        return latency
    except Exception as e:
        print(f"NLU Failed: {e}")
        return 0

def measure_rerank_latency():
    print("Measuring Rerank Latency (Long context)...")
    headers = {"Content-Type": "application/json"}
    # Simulate a longer context for reranking
    candidates = "ID 1: Product A\n" * 10
    data = {
        "contents": [{
            "parts": [{"text": f"Sort these:\n{candidates}"}]
        }]
    }
    
    start = time.time()
    try:
        response = requests.post(URL, headers=headers, json=data, timeout=10)
        end = time.time()
        latency = int((end - start) * 1000)
        print(f"Status: {response.status_code}")
        print(f"Rerank Latency: {latency}ms")
        return latency
    except Exception as e:
        print(f"Rerank Failed: {e}")
        return 0

if __name__ == "__main__":
    if not API_KEY:
        print("No API Key found")
    else:
        measure_nlu_latency()
        measure_rerank_latency()
