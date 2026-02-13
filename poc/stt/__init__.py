"""
STT Module — Compatibility Redirect Wrapper

This module redirects all imports to the canonical implementation
in poc/lsy/stt/. Do NOT add new code here; edit poc/lsy/stt/ instead.

Usage (unchanged from before):
    from poc.stt import get_adapter, WhisperAdapter, QualityGate, ...
    # These now resolve to poc.lsy.stt internally.
"""

# ── Re-export everything from the canonical poc.lsy.stt module ───────────────
from poc.lsy.stt import (  # noqa: F401
    BaseAdapter,
    WhisperAdapter,
    GoogleAdapter,
    get_adapter,
    QualityGate,
    PolicyGate,
    AudioConverter,
    normalize_audio,
    TextPostprocessor,
    AudioPreprocessor,
)

__all__ = [
    "BaseAdapter",
    "WhisperAdapter",
    "GoogleAdapter",
    "get_adapter",
    "QualityGate",
    "PolicyGate",
    "AudioConverter",
    "normalize_audio",
    "TextPostprocessor",
    "AudioPreprocessor",
]
