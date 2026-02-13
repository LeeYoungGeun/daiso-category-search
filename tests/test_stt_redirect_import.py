"""
STT Redirect Import Smoke Test

Verifies that all poc.stt.* imports resolve to poc.lsy.stt.* (the canonical
implementation). No external STT/audio/network calls — import-level only.
"""


def test_poc_stt_top_level_imports():
    """poc.stt top-level exports resolve to poc.lsy.stt."""
    from poc.stt import (
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
    # All should come from poc.lsy.stt
    assert BaseAdapter.__module__ == "poc.lsy.stt.adapters"
    assert WhisperAdapter.__module__ == "poc.lsy.stt.adapters"
    assert GoogleAdapter.__module__ == "poc.lsy.stt.adapters"
    assert get_adapter.__module__ == "poc.lsy.stt.adapters"
    assert QualityGate.__module__ == "poc.lsy.stt.quality_gate"
    assert PolicyGate.__module__ == "poc.lsy.stt.policy_gate"
    assert AudioConverter.__module__ == "poc.lsy.stt.audio_converter"
    assert normalize_audio.__module__ == "poc.lsy.stt.audio_converter"
    assert TextPostprocessor.__module__ == "poc.lsy.stt.text_postprocessor"
    assert AudioPreprocessor.__module__ == "poc.lsy.stt.audio_preprocessor"


def test_poc_stt_submodule_imports():
    """poc.stt.adapters / .types / .quality_gate etc. resolve to poc.lsy.stt.*."""
    from poc.stt.adapters import get_adapter as ga
    from poc.stt.types import STTResult, QualityGateResult, PolicyIntent
    from poc.stt.quality_gate import QualityGate as QG
    from poc.stt.policy_gate import PolicyGate as PG
    from poc.stt.audio_converter import AudioConverter as AC
    from poc.stt.text_postprocessor import TextPostprocessor as TP
    from poc.stt.audio_preprocessor import AudioPreprocessor as AP

    assert ga.__module__ == "poc.lsy.stt.adapters"
    assert STTResult.__module__ == "poc.lsy.stt.types"
    assert QualityGateResult.__module__ == "poc.lsy.stt.types"
    assert PolicyIntent.__module__ == "poc.lsy.stt.types"
    assert QG.__module__ == "poc.lsy.stt.quality_gate"
    assert PG.__module__ == "poc.lsy.stt.policy_gate"
    assert AC.__module__ == "poc.lsy.stt.audio_converter"
    assert TP.__module__ == "poc.lsy.stt.text_postprocessor"
    assert AP.__module__ == "poc.lsy.stt.audio_preprocessor"


def test_standard_entry_point_exists():
    """poc.lsy.stt.get_adapter is callable and defaults to 'whisper'."""
    from poc.lsy.stt import get_adapter

    assert callable(get_adapter)
    # Signature accepts provider="" (defaults to env/whisper)
    import inspect
    sig = inspect.signature(get_adapter)
    assert "provider" in sig.parameters
    # Default should be empty string (→ env lookup → "whisper")
    assert sig.parameters["provider"].default == ""
