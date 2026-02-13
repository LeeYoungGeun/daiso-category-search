"""
STT Module — Standard Speech-to-Text Pipeline Components (poc/lsy/stt)

This is the **canonical STT implementation**. All other STT references
(e.g. poc/stt, backend/api.py, backend/main.py) should resolve here
via the redirect wrapper in poc/stt/__init__.py.

Standard entry point:
    from poc.stt import get_adapter   # or from poc.lsy.stt import get_adapter
    adapter = get_adapter("whisper")  # local, no external API calls
    result  = adapter.transcribe("audio.wav")  # → STTResult

Provider control (env var):
    STT_PROVIDER=whisper   (default) — local faster-whisper, no external calls
    STT_PROVIDER=google    — Google Cloud Speech-to-Text (requires credentials)

Components:
    - WhisperAdapter / GoogleAdapter / get_adapter  — STT transcription
    - QualityGate      — STT output quality validation (R1→R4 rules)
    - PolicyGate       — Intent classification (PRODUCT_SEARCH / FIXED_LOCATION / UNSUPPORTED)
    - AudioConverter   — Audio normalization (→ WAV/PCM/16kHz/mono)
    - TextPostprocessor — STT text cleanup (filler removal, normalization)
    - AudioPreprocessor — Volume normalization + noise reduction
"""

from .adapters import BaseAdapter, WhisperAdapter, GoogleAdapter, get_adapter
from .quality_gate import QualityGate
from .policy_gate import PolicyGate
from .audio_converter import AudioConverter, normalize_audio
from .text_postprocessor import TextPostprocessor
from .audio_preprocessor import AudioPreprocessor

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
