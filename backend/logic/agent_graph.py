
import asyncio
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.logic.nlu import analyze_text, generate_tail_question, infer_product_keywords
from backend.database.database import search_products, get_related_products_for_context
from backend.logic.schemas import NLUResponse, Intent, NLUSlots, AmbiguityType
from backend.logic.ambiguity import (
    detect_ambiguity,
    calculate_category_spread,
    generate_clarification_options,
    build_clarification_question,
    should_fallback,
)
from backend.logic.reranker import rerank_candidates

# --- 1. Graph State Definition ---
class GraphState(TypedDict):
    request_id: str
    input_text: str             # Normalized user input
    session_id: str             # (Added for context handling)
    history: List[Dict]         # Conversation History [{"role": "user", "text": "..."}, ...]
    
    # NLU Result
    intent: Intent              # PRODUCT_LOCATION / OTHER / UNSUPPORTED
    slots: Dict[str, Any]       # {item, attrs, query_rewrite...}
    
    # Search Result
    search_candidates: List[Dict] # DB Search Results
    
    # M2: Ambiguity Detection
    is_ambiguous: bool          # Ambiguity Check Result
    ambiguity_type: str         # AmbiguityType value
    clarification_count: int    # Track clarification attempts (max 2 before fallback)
    is_fallback: bool           # Whether we're in fallback mode
    
    # M2: Reranking
    rerank_result: Dict[str, Any]  # Reranker output
    
    # Final Output
    final_response: NLUResponse # Structured Object for API

# --- 2. Nodes ---

async def nlu_node(state: GraphState):
    """Node 1: Parse User Input"""
    print(f"--- [Node: NLU] Analyzing: {state['input_text']} ---")
    
    # Pass history to NLU for context resolution
    history = state.get("history", [])
    nlu_result = await analyze_text(state['input_text'], history=history)
    
    return {
        "intent": nlu_result.intent,
        "slots": nlu_result.slots.model_dump(),
        # Pass the whole object as partial result
        "final_response": nlu_result 
    }

async def search_node(state: GraphState):
    """Node 2: Search DB"""
    if state["intent"] != Intent.PRODUCT_LOCATION:
        return {"search_candidates": []}
        
    slots = state["slots"]
    query = slots.get("item") or slots.get("query_rewrite") or ""
    print(f"--- [Node: Search] Querying: '{query}' ---")
    
    candidates = []
    if query:
        candidates = search_products(query)
    
    # If no results, try refined search (Rewrite Logic embedded here for robustness)
    if not candidates and query:
         print(f"    -> 0 results. attempting keyword inference...")
         keywords = await infer_product_keywords(state['input_text'])
         for kw in keywords:
             candidates.extend(search_products(kw))
             if candidates: break # stop if found
             
    print(f"    -> Found {len(candidates)} candidates")
    return {"search_candidates": candidates}

async def ambiguity_check_node(state: GraphState):
    """Node 3: M2 Enhanced Ambiguity Detection"""
    candidates = state["search_candidates"]
    intent = state["intent"]
    slots = state["slots"]
    
    # Non-product intents are not ambiguous (handled in response node)
    if intent == Intent.UNSUPPORTED or intent == Intent.OTHER_INQUIRY:
        return {
            "is_ambiguous": False,
            "ambiguity_type": AmbiguityType.NONE.value,
            "is_fallback": False,
        }
    
    # M2: Use structured ambiguity detection
    category_spread = calculate_category_spread(candidates)
    ambiguity_result = detect_ambiguity(
        item=slots.get("item"),
        attrs=slots.get("attrs", []),
        candidates_count=len(candidates),
        category_spread=category_spread,
        nlu_needs_clarification=state["final_response"].needs_clarification,
    )
    
    is_ambiguous = ambiguity_result.is_ambiguous
    
    # M2: 2-strike fallback check
    clarification_count = state.get("clarification_count", 0)
    is_fallback = False
    
    if is_ambiguous and should_fallback(clarification_count):
        print("--- [Node: Ambiguity] 2-strike fallback triggered. Forcing answer. ---")
        is_ambiguous = False  # Don't ask, just answer
        is_fallback = True
    
    # Loop prevention: if previous turn was a question, don't ask again
    history = state.get("history", [])
    if is_ambiguous and history and history[-1]["role"] == "assistant":
        last_msg = history[-1]["text"]
        if "?" in last_msg or "어떤" in last_msg or "입니까" in last_msg:
            print("--- [Node: Ambiguity] Loop Detected (Prev was Question). Forcing Answer. ---")
            is_ambiguous = False
            is_fallback = True
        
    print(f"--- [Node: Ambiguity] Type={ambiguity_result.ambiguity_type.value}, "
          f"Ambiguous={is_ambiguous}, Fallback={is_fallback} ---")
    
    return {
        "is_ambiguous": is_ambiguous,
        "ambiguity_type": ambiguity_result.ambiguity_type.value,
        "is_fallback": is_fallback,
    }

async def rerank_node(state: GraphState):
    """Node 3b: M2 Reranking with confidence scoring"""
    candidates = state["search_candidates"]
    
    if not candidates:
        return {"rerank_result": {"selected_id": None, "reason": "", "confidence": 0.0}}
    
    # Prepare candidates for reranking
    rerank_input = []
    for c in candidates[:10]:  # Limit to top 10
        rerank_input.append({
            "id": str(c.get("id", "")),
            "name": c.get("name", ""),
            "desc": c.get("searchable_desc", c.get("text", c.get("name", ""))),
        })
    
    result = rerank_candidates(state["input_text"], rerank_input)
    print(f"--- [Node: Rerank] Selected: {result.get('selected_id')}, "
          f"Confidence: {result.get('confidence', 0):.2f} ---")
    
    return {"rerank_result": result}

async def clarification_node(state: GraphState):
    """Node 4: M2 Enhanced Clarification with structured options"""
    print(f"--- [Node: Clarification] Generating Question ---")
    
    candidates = state["search_candidates"]
    slots = state["slots"]
    
    # M2: Generate structured clarification options
    options = generate_clarification_options(candidates, item=slots.get("item"))
    question = build_clarification_question(slots.get("item"), options)
    
    # Update Final Response
    resp = state["final_response"]
    resp.needs_clarification = True
    resp.generated_question = question
    resp.products = candidates  # Show what we found even if asking
    
    return {
        "final_response": resp,
        "clarification_count": state.get("clarification_count", 0) + 1,
    }

async def response_node(state: GraphState):
    """Node 5: Finalize Answer with M2 reranking"""
    print(f"--- [Node: Response] Finalizing ---")
    resp = state["final_response"]
    candidates = state["search_candidates"]
    rerank_result = state.get("rerank_result", {})
    
    # Reorder candidates based on reranking
    selected_id = rerank_result.get("selected_id")
    if selected_id and candidates:
        # Move selected candidate to front
        reordered = []
        selected = None
        for c in candidates:
            if str(c.get("id", "")) == str(selected_id):
                selected = c
            else:
                reordered.append(c)
        if selected:
            reordered.insert(0, selected)
        resp.products = reordered
    else:
        resp.products = candidates
    
    if state["intent"] == Intent.UNSUPPORTED:
        resp.generated_question = "죄송합니다. 상품 찾기 외의 질문은 아직 답변하기 어렵습니다."
        resp.needs_clarification = True
    elif state.get("is_fallback"):
        # M2: Fallback message
        query = state['input_text']
        count = len(resp.products)
        resp.generated_question = f"정확한 상품을 찾기 어려워 가장 관련 있는 상품 {count}개를 안내해 드립니다."
    elif not resp.generated_question and resp.products:
        query = state['input_text']
        count = len(resp.products)
        resp.generated_question = f"요청하신 '{query}' 관련 상품 {count}개를 찾았습니다."
        
    return {"final_response": resp}

# --- 3. Edges ---

def route_after_ambiguity(state: GraphState):
    if state["is_ambiguous"]:
        # Limit Loop: If we already asked once (or purely logic check)
        if state.get("clarification_count", 0) >= 1:
            return "rerank"  # Skip clarification, go to rerank
        return "clarification"
    return "rerank"  # M2: Always rerank before response

# --- 4. Graph Construction ---

workflow = StateGraph(GraphState)

workflow.add_node("nlu", nlu_node)
workflow.add_node("search", search_node)
workflow.add_node("ambiguity_check", ambiguity_check_node)
workflow.add_node("rerank", rerank_node)
workflow.add_node("clarification", clarification_node)
workflow.add_node("final_response", response_node)

workflow.set_entry_point("nlu")

workflow.add_edge("nlu", "search")
workflow.add_edge("search", "ambiguity_check")
workflow.add_conditional_edges(
    "ambiguity_check",
    route_after_ambiguity,
    {
        "clarification": "clarification",
        "rerank": "rerank"
    }
)
workflow.add_edge("rerank", "final_response")
workflow.add_edge("clarification", END)
workflow.add_edge("final_response", END)

memory = MemorySaver()
agent_app = workflow.compile(checkpointer=memory)
