# backend/stt/audio_converter.py
"""
Audio Format Converter
Normalizes all audio inputs to standard format: WAV / PCM LINEAR16 / 16kHz / mono
"""

import os
import shutil
import subprocess
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Add FFmpeg to PATH (Temporary fix for Windows)
ffmpeg_path = r"C:\Users\301\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
if os.path.exists(ffmpeg_path):
    os.environ["PATH"] += os.pathsep + ffmpeg_path

from pydub import AudioSegment


class AudioConverter:
    """
    Converts audio files to standard STT format:
    - Format: WAV
    - Codec: PCM LINEAR16
    - Sample Rate: 16000 Hz
    - Channels: 1 (mono)
    """
    
    STANDARD_FORMAT = "wav"
    STANDARD_SAMPLE_RATE = 16000
    STANDARD_CHANNELS = 1
    STANDARD_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
    
    SUPPORTED_FORMATS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".opus"}
    
    def __init__(self, output_dir: str = "outputs/normalized"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def get_audio_metadata(self, audio_path: str) -> Dict:
        """Extract audio file metadata"""
        path = Path(audio_path)
        
        try:
            audio = AudioSegment.from_file(audio_path)
            return {
                "original": {
                    "format": path.suffix[1:].lower(),
                    "sample_rate": audio.frame_rate,
                    "channels": audio.channels,
                    "sample_width": audio.sample_width,
                    "duration_sec": round(len(audio) / 1000, 2),
                    "file_size_bytes": path.stat().st_size
                }
            }
        except Exception as e:
            return {
                "original": {
                    "format": path.suffix[1:].lower(),
                    "file_size_bytes": path.stat().st_size if path.exists() else 0,
                    "error": str(e)
                }
            }
    
    def normalize(self, audio_path: str, preserve_original: bool = True) -> Dict:
        """
        Convert audio to standard format (WAV/PCM/16kHz/mono)
        
        Returns:
            Dict with normalized file path and conversion metadata
        """
        start_time = time.time()
        input_path = Path(audio_path)
        
        # Validate input
        if not input_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        if input_path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {input_path.suffix}. Supported: {self.SUPPORTED_FORMATS}")
        
        # Get original metadata
        original_metadata = self.get_audio_metadata(audio_path)
        
        # Load audio
        audio = AudioSegment.from_file(audio_path)
        
        # Check if conversion is needed
        needs_conversion = (
            audio.frame_rate != self.STANDARD_SAMPLE_RATE or
            audio.channels != self.STANDARD_CHANNELS or
            audio.sample_width != self.STANDARD_SAMPLE_WIDTH or
            input_path.suffix.lower() != f".{self.STANDARD_FORMAT}"
        )
        
        if needs_conversion:
            # Convert to standard format
            audio = audio.set_frame_rate(self.STANDARD_SAMPLE_RATE)
            audio = audio.set_channels(self.STANDARD_CHANNELS)
            audio = audio.set_sample_width(self.STANDARD_SAMPLE_WIDTH)
            
            # Output path
            output_filename = f"{input_path.stem}.wav"
            output_path = self.output_dir / output_filename
            
            # Export as WAV PCM
            audio.export(
                output_path,
                format="wav",
                parameters=["-acodec", "pcm_s16le"]
            )
        else:
            # No conversion needed, use original
            output_path = input_path
        
        conversion_time = int((time.time() - start_time) * 1000)
        
        # Build result metadata
        result = {
            "audio_metadata": {
                "original": original_metadata.get("original", {}),
                "normalized": {
                    "format": "wav",
                    "codec": "pcm_s16le",
                    "sample_rate": self.STANDARD_SAMPLE_RATE,
                    "channels": self.STANDARD_CHANNELS,
                    "bit_depth": 16,
                    "duration_sec": round(len(audio) / 1000, 2),
                    "file_size_bytes": output_path.stat().st_size,
                    "path": str(output_path)
                },
                "conversion": {
                    "required": needs_conversion,
                    "method": "pydub+ffmpeg" if needs_conversion else "none",
                    "conversion_time_ms": conversion_time
                }
            },
            "normalized_path": str(output_path)
        }
        
        return result
    
    def is_supported(self, file_path: str) -> bool:
        """Check if file format is supported"""
        return Path(file_path).suffix.lower() in self.SUPPORTED_FORMATS


# Module-level converter instance
_converter: Optional[AudioConverter] = None

def get_converter(output_dir: str = "outputs/normalized") -> AudioConverter:
    """Get or create AudioConverter singleton"""
    global _converter
    if _converter is None:
        _converter = AudioConverter(output_dir)
    return _converter


def normalize_audio(audio_path: str) -> Dict:
    """Convenience function to normalize audio"""
    return get_converter().normalize(audio_path)
