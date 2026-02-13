# backend/ws_stt.py
"""
WebSocket endpoint for real-time streaming STT — Redirect Wrapper.

This module redirects to the canonical implementation in poc/lsy/ws_stt.py,
which includes:
  - Google Cloud Speech-to-Text v1 streaming
  - Whisper fallback (when Google returns no final result)
  - Audio ring buffer (always-on, configurable max duration)
  - Text postprocessing (filler removal, normalization)
  - CSV logging for test results

Usage (unchanged):
    from backend.ws_stt import handle_streaming_stt
    # In FastAPI:
    @app.websocket("/ws/stt")
    async def ws_stt(websocket: WebSocket):
        await handle_streaming_stt(websocket)

The original legacy implementation is preserved in git history.
Do NOT add new STT logic here; edit poc/lsy/ws_stt.py instead.
"""

from poc.lsy.ws_stt import handle_streaming_stt  # noqa: F401

__all__ = ["handle_streaming_stt"]
