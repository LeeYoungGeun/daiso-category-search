
import os
import json
import uuid
import time
import datetime
import asyncio
from typing import List, Dict
from dotenv import load_dotenv
from .schemas import NLUResponse, Intent, NLUSlots
from .prompts import SYSTEM_PROMPT_V1, TAIL_QUESTION_PROMPT, AUX_PROMPT_KEYWORDS, KEYWORD_EXPANSION_PROMPT

load_dotenv()

_client = None
MODEL_NAME = "gemini-2.0-flash-001"

def get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        api_key = os.getenv("GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client

def log_debug(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    print(f"[{timestamp}] {msg}")
    try:
        with open("nlu_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except:
        pass

async def analyze_text(text: str, history: List[Dict[str, str]] = []) -> NLUResponse:
    request_id = str(uuid.uuid4())
    start_time = time.time()
    
    log_debug(f"[{request_id}] Analyzing: {text} | History: {len(history)} turns")

    # Format History
    history_text = ""
    if history:
        history_text = "## Conversation History\n"
        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("text") or turn.get("content", "")
            history_text += f"{role}: {content}\n"
    
    try:
        from google.genai import types
        
        client = get_client()
        
        # Combine System Prompt + History + Current Input
        final_prompt = f"{history_text}\nUser's Current Input: {text}"
        
        # Async call with new API
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=MODEL_NAME,
                contents=final_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_V1,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            ),
            timeout=5.0
        )
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        if hasattr(response, "usage_metadata") and response.usage_metadata:
             usage["prompt_tokens"] = response.usage_metadata.prompt_token_count or 0
             usage["completion_tokens"] = response.usage_metadata.candidates_token_count or 0
             usage["total_tokens"] = response.usage_metadata.total_token_count or 0
        
        # Fallback Estimation
        response_text = response.text or ""
        if usage.get("total_tokens", 0) == 0:
             usage["prompt_tokens"] = max(1, len(final_prompt) // 4)
             usage["completion_tokens"] = max(1, len(response_text) // 4)
             usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        data = json.loads(response_text)
        
        intent_val = data.get("intent", "UNSUPPORTED")
        if intent_val not in Intent.__members__:
            intent_val = "UNSUPPORTED"
            
        return NLUResponse(
            request_id=request_id,
            intent=Intent[intent_val],
            slots=NLUSlots(**data.get("slots", {})),
            needs_clarification=data.get("needs_clarification", False),
            latency_ms=latency_ms,
            token_usage=usage
        )

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_debug(f"[{request_id}] Error: {e}")
        return NLUResponse(
            request_id=request_id,
            intent=Intent.UNSUPPORTED,
            slots=NLUSlots(),
            needs_clarification=False,
            generated_question=f"Error: {str(e)}",
            latency_ms=latency_ms
        )

async def generate_tail_question(context: str, slots: dict, db_context: str = "") -> str:
    try:
        from google.genai import types
        
        client = get_client()
        
        formatted_prompt = TAIL_QUESTION_PROMPT.format(
            context=context,
            slots=json.dumps(slots, ensure_ascii=False),
            db_context=db_context
        )
        
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_NAME,
            contents=formatted_prompt
        )
        return (response.text or "").strip()
    except Exception:
        return "자세히 말씀해 주시면 찾아드릴게요."

async def infer_product_keywords(text: str, return_usage: bool = False) -> list[str] | tuple[list[str], dict]:
    try:
        from google.genai import types
        
        client = get_client()
        prompt = AUX_PROMPT_KEYWORDS.format(text=text)
        
        # Capture response object to get usage
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
             usage["prompt_tokens"] = response.usage_metadata.prompt_token_count or 0
             usage["completion_tokens"] = response.usage_metadata.candidates_token_count or 0
             usage["total_tokens"] = response.usage_metadata.total_token_count or 0
        
        # Fallback Estimation
        response_text = response.text or ""
        if usage.get("total_tokens", 0) == 0:
             usage["prompt_tokens"] = max(1, len(prompt) // 4)
             usage["completion_tokens"] = max(1, len(response_text) // 4)
             usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        
        keywords = json.loads(response_text)
        if not isinstance(keywords, list): keywords = []
        
        if return_usage:
            return keywords, usage
        return keywords
        
    except Exception as e:
        log_debug(f"Inference error: {e}")
        empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if return_usage:
            return [], empty_usage
        return []

async def expand_search_keywords(product_name: str, return_usage: bool = False) -> List[str] | tuple[List[str], dict]:
    try:
        from google.genai import types
        
        client = get_client()
        prompt = KEYWORD_EXPANSION_PROMPT.format(product_name=product_name)
        
        start_time = time.time()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        end_time = time.time()
        latency = end_time - start_time
        
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": latency
        }
        if hasattr(response, "usage_metadata") and response.usage_metadata:
             usage["prompt_tokens"] = response.usage_metadata.prompt_token_count or 0
             usage["completion_tokens"] = response.usage_metadata.candidates_token_count or 0
             usage["total_tokens"] = response.usage_metadata.total_token_count or 0
             
        # Fallback Estimation
        response_text = response.text or ""
        if usage.get("total_tokens", 0) == 0:
             usage["prompt_tokens"] = max(1, len(prompt) // 4)
             usage["completion_tokens"] = max(1, len(response_text) // 4)
             usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
             
        keywords = json.loads(response_text)
        if not isinstance(keywords, list): keywords = [product_name]
        
        if return_usage:
            return keywords, usage
        return keywords

    except Exception as e:
        log_debug(f"Keyword expansion error for {product_name}: {e}")
        empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if return_usage:
             return [product_name], empty_usage
        return [product_name]
