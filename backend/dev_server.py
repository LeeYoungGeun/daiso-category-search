# backend/dev_server.py
"""
Lightweight dev server for frontend development
Provides /v1/search endpoint using SQLite fallback (no Whisper/Google STT required)
Provides /ml/rerank endpoint for QPM load-testing the ML rerank layer
"""

import sys
import os
import time
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure project root is in path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set UTF-8 encoding for Windows
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ============================================================================
# Request/Response Models
# ============================================================================

class SearchRequest(BaseModel):
    store_id: str = Field(default="store_001")
    input_type: str = Field(default="text")
    query: str = Field(...)
    session_id: Optional[str] = Field(default=None)
    history: Optional[List[Dict[str, str]]] = Field(default=None)
    clarification_count: int = Field(default=0)


class SearchResponse(BaseModel):
    request_id: str
    query: str
    is_in_scope: bool
    intent: Optional[str] = None
    top3: List[Dict[str, Any]] = []
    top1_handover: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    clarification_options: List[str] = []
    clarification_count: int = 0
    is_fallback: bool = False
    timing_ms: Dict[str, int] = {}
    metadata: Dict[str, Any] = {}
    error: Optional[str] = None


# ============================================================================
# App
# ============================================================================

app = FastAPI(
    title="Daiso Category Search - Dev Server",
    description="Lightweight dev server for frontend development",
    version="dev"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Try to initialize the search pipeline (force SQLite mode for DB consistency)
search_pipeline = None
try:
    from backend.logic.integrated_search import get_pipeline
    search_pipeline = get_pipeline()
    # Force SQLite mode so results match products.db
    search_pipeline._use_hybrid = False
    search_pipeline._hybrid_service = None
    print("[DEV] Integrated search pipeline initialized (forced mode:", search_pipeline.search_mode, ")")
except Exception as e:
    print(f"[DEV] WARNING: Could not initialize integrated search pipeline: {e}")
    print("[DEV] Falling back to direct SQLite search")


@app.get("/")
def root():
    return {
        "service": "Daiso Category Search (Dev)",
        "version": "dev",
        "status": "running",
        "search_pipeline": search_pipeline is not None,
        "search_mode": search_pipeline.search_mode if search_pipeline else "direct_sqlite",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "search_pipeline": search_pipeline is not None,
        "mode": "dev",
    }


@app.post("/v1/search", response_model=SearchResponse)
async def search_endpoint(request: SearchRequest):
    """Search endpoint - uses integrated pipeline or direct SQLite fallback"""
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]

    try:
        if search_pipeline:
            # Use full integrated pipeline
            result = await search_pipeline.search(
                query=request.query,
                store_id=request.store_id,
                session_id=request.session_id,
                history=request.history or [],
                clarification_count=request.clarification_count,
            )
            return SearchResponse(**result)
        else:
            # Direct SQLite fallback
            return await _direct_sqlite_search(request, request_id, start_time)

    except Exception as e:
        logging.error(f"Search error: {e}", exc_info=True)
        total_time = int((time.time() - start_time) * 1000)
        return SearchResponse(
            request_id=request_id,
            query=request.query,
            is_in_scope=True,
            message=f"Search error: {str(e)}",
            timing_ms={"total": total_time},
            metadata={"error_type": type(e).__name__},
            error=str(e),
        )


async def _direct_sqlite_search(
    request: SearchRequest, request_id: str, start_time: float
) -> SearchResponse:
    """Direct SQLite search without NLU/Reranking"""
    from backend.database.database import search_products
    from backend.database.category_matcher import match_product_to_category

    search_start = time.time()
    candidates = search_products(request.query)
    search_time = int((time.time() - search_start) * 1000)

    if not candidates:
        total_time = int((time.time() - start_time) * 1000)
        return SearchResponse(
            request_id=request_id,
            query=request.query,
            is_in_scope=True,
            message=f"'{request.query}' 관련 상품을 찾을 수 없습니다.",
            timing_ms={"search": search_time, "total": total_time},
            metadata={"search_mode": "direct_sqlite"},
        )

    # Format top 3
    top3 = []
    for idx, c in enumerate(candidates[:3]):
        major, middle = match_product_to_category(c["name"])
        product_data = {
            "product_id": c["id"],
            "name": c["name"],
            "price": c.get("price", 0),
            "category_major": c.get("category", major),
            "category_middle": middle,
            "location_text": f"{c.get('category', major)} > {middle}",
            "image_url": c.get("image_url"),
            "rank": idx + 1,
            "is_top1": idx == 0,
        }
        top3.append(product_data)

    # QR handover for top1
    top1 = top3[0] if top3 else None
    top1_handover = None
    if top1:
        top1_handover = {
            "qr_payload": f"https://daiso.app/product/{top1['product_id']}",
            "expires_in_sec": 120,
            "product_id": top1["product_id"],
            "product_name": top1["name"],
        }

    total_time = int((time.time() - start_time) * 1000)

    return SearchResponse(
        request_id=request_id,
        query=request.query,
        is_in_scope=True,
        intent="PRODUCT_SEARCH",
        top3=top3,
        top1_handover=top1_handover,
        message=f"'{request.query}' 관련 상품 {len(top3)}개를 찾았습니다.",
        timing_ms={"search": search_time, "total": total_time},
        metadata={"search_mode": "direct_sqlite"},
    )


# ============================================================================
# ML Rerank Endpoint — thin layer for QPM load-testing
# ============================================================================

class RerankRequest(BaseModel):
    query: str = Field(...)
    candidates: List[Dict[str, Any]] = Field(default=[])
    timeout: float = Field(default=5.0)


class RerankResponse(BaseModel):
    selected_id: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0
    latency_ms: int = 0
    is_fallback: bool = False
    error_type: Optional[str] = None


@app.post("/ml/rerank")
async def ml_rerank_endpoint(request: RerankRequest):
    """
    ML Rerank endpoint — exposes M2 reranker via HTTP for QPM load-testing.
    Controlled by RERANK_MODE env var (mock|vendor).
    """
    from backend.ml.rerank_service import RerankService

    svc = RerankService()  # reads RERANK_MODE from env
    result = svc.rerank(
        query=request.query,
        candidates=request.candidates,
        timeout=request.timeout,
    )
    response = JSONResponse(content=result)
    response.headers["X-Rerank-Latency-Ms"] = str(result.get("latency_ms", 0))
    return response


# Dummy WebSocket endpoint for STT (returns error gracefully)
@app.websocket("/ws/stt")
async def websocket_stt_endpoint(websocket: WebSocket):
    """Dummy STT WebSocket - returns error since STT is not available in dev mode"""
    await websocket.accept()
    import json
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "start":
                await websocket.send_json({
                    "type": "error",
                    "message": "STT is not available in dev mode. Please use text search."
                })
            elif msg.get("type") == "stop":
                break
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
