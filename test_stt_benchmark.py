
import time
import os
import sys
from pathlib import Path
import asyncio

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from poc.stt.adapters import get_adapter
from poc.stt.quality_gate import QualityGate
from poc.stt.audio_converter import AudioConverter
import yaml

async def test_stt():
    print("="*50)
    print("STT Benchmark")
    print("="*50)
    
    # Load Config
    with open("backend/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Initialize Components
    print("Initializing STT Components...")
    start_init = time.time()
    
    # Audio Converter
    audio_converter = AudioConverter(output_dir="outputs/normalized")
    
    # STT Adapter (Whisper)
    adapter = get_adapter("whisper", **config["stt"]["whisper"])
    
    # Quality Gate
    quality_gate = QualityGate(**config["quality_gate"])
    
    init_time = int((time.time() - start_init) * 1000)
    print(f"[Init] Time: {init_time}ms")
    
    # Test File
    test_file = "data/test_audio/01_general/김동국_일반1.m4a"
    if not os.path.exists(test_file):
        print(f"File not found: {test_file}")
        # Search for any file
        for root, dirs, files in os.walk("data/test_audio"):
            for file in files:
                if file.endswith(".m4a") or file.endswith(".wav"):
                    test_file = os.path.join(root, file)
                    break
            if os.path.exists(test_file): break
    
    print(f"Target File: {test_file}")
    
    # Step 1: Normalization
    print("\n[Step 1] Audio Normalization")
    t0 = time.time()
    conversion_result = audio_converter.normalize(test_file)
    normalized_path = conversion_result["normalized_path"]
    t_norm = int((time.time() - t0) * 1000)
    print(f"  - Path: {normalized_path}")
    print(f"  - Time: {t_norm}ms")
    
    # Step 2: STT Transcribe
    print("\n[Step 2] STT Transcription")
    t0 = time.time()
    stt_result = adapter.transcribe(normalized_path)
    t_stt = int((time.time() - t0) * 1000)
    print(f"  - Text: {stt_result.text_raw}")
    print(f"  - Time: {t_stt}ms")
    
    # Step 3: Quality Gate
    print("\n[Step 3] Quality Gate")
    t0 = time.time()
    quality_result = quality_gate.evaluate(stt_result, attempt=1)
    t_quality = int((time.time() - t0) * 1000)
    print(f"  - Status: {quality_result.status}")
    print(f"  - Time: {t_quality}ms")
    
    # Total
    total_time = t_norm + t_stt + t_quality
    print(f"\n[Total STT Pipeline] {total_time}ms")

if __name__ == "__main__":
    asyncio.run(test_stt())
