# backend/stt/audio_preprocessor.py
"""
오디오 전처리 모듈
- 볼륨 정규화 (-20 dBFS)
- 노이즈 제거 (옵션, noisereduce)
"""

import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# pydub for volume normalization
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# noisereduce is optional
try:
    import noisereduce as nr
    import numpy as np
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    NOISEREDUCE_AVAILABLE = False


class AudioPreprocessor:
    """오디오 전처리 - AudioConverter 이전 단계"""
    
    def __init__(self, output_dir: str = "outputs/preprocessed"):
        """
        Args:
            output_dir: 전처리된 파일 저장 경로
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def normalize_volume(
        self, 
        audio_path: str, 
        target_dBFS: float = -20.0
    ) -> Tuple[str, bool]:
        """
        볼륨 정규화
        
        Args:
            audio_path: 입력 오디오 파일 경로
            target_dBFS: 목표 dBFS (기본 -20)
        
        Returns:
            (출력 파일 경로, 성공 여부)
        """
        if not PYDUB_AVAILABLE:
            return audio_path, False
        
        try:
            audio = AudioSegment.from_file(audio_path)
            
            # 현재 dBFS 확인
            current_dBFS = audio.dBFS
            
            # 볼륨 조정 필요량 계산
            change_in_dBFS = target_dBFS - current_dBFS
            
            # 볼륨 조정 (너무 큰 변화는 제한)
            if abs(change_in_dBFS) > 30:
                change_in_dBFS = 30 if change_in_dBFS > 0 else -30
            
            normalized_audio = audio.apply_gain(change_in_dBFS)
            
            return normalized_audio, True
            
        except Exception:
            return None, False
    
    def reduce_noise(
        self, 
        audio_segment: "AudioSegment"
    ) -> Tuple["AudioSegment", bool]:
        """
        노이즈 제거 (noisereduce 사용)
        
        Args:
            audio_segment: pydub AudioSegment
        
        Returns:
            (처리된 AudioSegment, 성공 여부)
        """
        if not NOISEREDUCE_AVAILABLE or not PYDUB_AVAILABLE:
            return audio_segment, False
        
        try:
            # AudioSegment → numpy array
            samples = np.array(audio_segment.get_array_of_samples())
            sample_rate = audio_segment.frame_rate
            
            # 노이즈 제거
            reduced = nr.reduce_noise(
                y=samples.astype(np.float32),
                sr=sample_rate,
                prop_decrease=0.8,  # 노이즈 감소 비율 (0.0 ~ 1.0)
                stationary=True
            )
            
            # numpy array → AudioSegment
            reduced_audio = audio_segment._spawn(
                reduced.astype(np.int16).tobytes()
            )
            
            return reduced_audio, True
            
        except Exception:
            return audio_segment, False
    
    def preprocess(
        self, 
        audio_path: str, 
        config: Dict,
        test_id: str,
        provider: str
    ) -> Tuple[str, Dict]:
        """
        전처리 파이프라인
        
        Args:
            audio_path: 입력 오디오 파일 경로
            config: 전처리 설정
                - volume_normalize: bool (기본 True)
                - target_dBFS: float (기본 -20)
                - noise_reduction: bool (기본 False)
            test_id: 테스트 ID (파일명 충돌 방지용)
            provider: STT 제공자 (whisper/google)
        
        Returns:
            (전처리된 파일 경로, 메타데이터)
        """
        start_time = time.time()
        
        metadata = {
            "preprocessing_executed": False,
            "volume_normalized": False,
            "noise_reduced": False,
            "preprocessing_time_ms": 0,
            "original_path": audio_path
        }
        
        # pydub 없으면 원본 반환
        if not PYDUB_AVAILABLE:
            metadata["preprocessing_time_ms"] = int((time.time() - start_time) * 1000)
            return audio_path, metadata
        
        try:
            # 설정 읽기
            do_volume = config.get("volume_normalize", True)
            target_dBFS = config.get("target_dBFS", -20.0)
            do_noise = config.get("noise_reduction", False)
            
            # 아무 전처리도 안 하면 원본 반환
            if not do_volume and not do_noise:
                metadata["preprocessing_time_ms"] = int((time.time() - start_time) * 1000)
                return audio_path, metadata
            
            metadata["preprocessing_executed"] = True
            
            # 오디오 로드
            audio = AudioSegment.from_file(audio_path)
            
            # 1. 볼륨 정규화
            if do_volume:
                current_dBFS = audio.dBFS
                change_in_dBFS = target_dBFS - current_dBFS
                
                # 너무 큰 변화 제한
                if abs(change_in_dBFS) > 30:
                    change_in_dBFS = 30 if change_in_dBFS > 0 else -30
                
                audio = audio.apply_gain(change_in_dBFS)
                metadata["volume_normalized"] = True
            
            # 2. 노이즈 제거 (옵션)
            if do_noise and NOISEREDUCE_AVAILABLE:
                audio, success = self.reduce_noise(audio)
                metadata["noise_reduced"] = success
            
            # 출력 파일명 생성 (충돌 방지)
            stem = Path(audio_path).stem
            output_filename = f"{test_id}_{provider}_{stem}.wav"
            output_path = self.output_dir / output_filename
            
            # WAV로 저장 (16kHz, mono로 통일)
            audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(str(output_path), format="wav")
            
            metadata["preprocessing_time_ms"] = int((time.time() - start_time) * 1000)
            
            return str(output_path), metadata
            
        except Exception as e:
            # 실패 시 원본 반환
            metadata["preprocessing_time_ms"] = int((time.time() - start_time) * 1000)
            metadata["error"] = str(e)
            return audio_path, metadata
