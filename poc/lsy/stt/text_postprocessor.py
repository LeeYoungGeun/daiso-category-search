# backend/stt/text_postprocessor.py
"""
STT 결과 텍스트 후처리 모듈
- 추임새/수사 제거 (옵션)
- 단위/숫자 정규화
- 공백/구두점 정리
"""

import re
from typing import Dict, Optional


class TextPostprocessor:
    """STT 결과 텍스트 후처리 (normalize_ko 이전에 적용)"""

    # 기본 추임새/수사 패턴
    DEFAULT_FILLER_PATTERNS = [
        r"^(음+|어+|그+|저+|아+)[\.…,\s]*",      # 시작 수사: 음..., 어..., 그...
        r"(있잖아요?|그러니까|뭐랄까|근데요?)",   # 추임새
        r"[\s]+(음|어|그|저)+[\s]+",             # 중간 수사 (공백 사이)
        r"(에+|으+)[\.…,\s]*$",                  # 끝부분 수사
    ]

    # 기본 단위 변환 규칙 (목표: 표준 표기: ml, g, kg, cm, mm, l)
    # ⚠️ 주의:
    # - "밀리"는 용량(ml) 의미가 매우 잦아 mm로 처리하지 않음 (오탐 위험)
    # - "엘"은 오탐 가능성이 있어 기본 OFF에 가깝게 보수적으로 처리(숫자+엘만)
    DEFAULT_UNIT_MAPPINGS = {
        # --------------------
        # ml 계열: 미리/밀리/밀리리터/mL/ml/띄어쓴 m l -> ml
        # --------------------
        r"(\d+)\s*(미리|밀리)(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1ml",
        r"(\d+)\s*밀리리터(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1ml",
        r"(\d+)\s*m\s*l(?=\s|$|[^a-zA-Z0-9])": r"\1ml",
        r"(\d+)\s*mL(?=\s|$|[^a-zA-Z0-9])": r"\1ml",
        r"(\d+)\s*ml(?=\s|$|[^a-zA-Z0-9])": r"\1ml",

        # --------------------
        # g 계열: 그램/g -> g
        # --------------------
        r"(\d+)\s*그램(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1g",
        r"(\d+)\s*g(?=\s|$|[^a-zA-Z0-9])": r"\1g",

        # --------------------
        # kg 계열: 킬로/킬로그램/kg -> kg
        # --------------------
        r"(\d+)\s*(킬로그램|킬로)(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1kg",
        r"(\d+)\s*kg(?=\s|$|[^a-zA-Z0-9])": r"\1kg",

        # --------------------
        # cm 계열: 센치/센티/센티미터/cm -> cm
        # --------------------
        r"(\d+)\s*(센치|센티)(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1cm",
        r"(\d+)\s*센티미터(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1cm",
        r"(\d+)\s*cm(?=\s|$|[^a-zA-Z0-9])": r"\1cm",

        # --------------------
        # mm 계열: 밀리미터/mm -> mm
        # (※ "밀리" 단독은 ml 의미가 많아 mm로 바꾸지 않음)
        # --------------------
        r"(\d+)\s*밀리미터(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1mm",
        r"(\d+)\s*mm(?=\s|$|[^a-zA-Z0-9])": r"\1mm",

        # --------------------
        # L 계열: 리터/l/L -> l
        # "엘"은 숫자 바로 뒤에서만 허용(보수적)
        # --------------------
        r"(\d+)\s*리터(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1l",
        r"(\d+)\s*[lL](?=\s|$|[^a-zA-Z0-9])": r"\1l",
        r"(\d+)\s*엘(?=\s|$|[^가-힣a-zA-Z0-9])": r"\1l",  # 필요 없으면 이 줄 주석 처리
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: 후처리 설정 (기본값 사용 시 None)
        """
        self.config = config or {}

        # 패턴/매핑 설정 (config에서 override 가능)
        self.filler_patterns = self.config.get(
            "filler_patterns",
            self.DEFAULT_FILLER_PATTERNS
        )
        self.unit_mappings = self.config.get(
            "unit_mappings",
            self.DEFAULT_UNIT_MAPPINGS
        )

    def remove_fillers(self, text: str) -> str:
        """추임새/수사 제거"""
        if not text:
            return text

        result = text
        for pattern in self.filler_patterns:
            result = re.sub(pattern, " ", result, flags=re.IGNORECASE)

        return result.strip()

    def normalize_units(self, text: str) -> str:
        """단위/숫자 정규화"""
        if not text:
            return text

        result = text
        for pattern, replacement in self.unit_mappings.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        return result

    def cleanup_whitespace(self, text: str) -> str:
        """공백/구두점 정리"""
        if not text:
            return text

        # 연속 공백 → 단일 공백
        result = re.sub(r"\s+", " ", text)

        # 불필요한 구두점 정리 (연속된 마침표, 쉼표 등)
        result = re.sub(r"[\.]{2,}", ".", result)
        result = re.sub(r"[,]{2,}", ",", result)
        result = re.sub(r"[\.…]+\s*$", "", result)  # 문장 끝 말줄임 제거

        return result.strip()

    def postprocess(self, text: str, config: Optional[Dict] = None) -> str:
        """
        전체 후처리 파이프라인

        순서: (1) 추임새 제거 → (2) 단위/숫자 정규화 → (3) 공백 정리

        Args:
            text: STT 원문 텍스트
            config: 런타임 설정 override (선택)
                - remove_fillers: bool (기본 True)
                - normalize_units: bool (기본 True)
                - cleanup_whitespace: bool (기본 True)

        Returns:
            후처리된 텍스트
        """
        if not text:
            return text

        # 런타임 config merge
        runtime_config = {**self.config, **(config or {})}

        result = text

        # 1. 추임새/수사 제거
        if runtime_config.get("remove_fillers", True):
            result = self.remove_fillers(result)

        # 2. 단위/숫자 정규화
        if runtime_config.get("normalize_units", True):
            result = self.normalize_units(result)

        # 3. 공백/구두점 정리
        if runtime_config.get("cleanup_whitespace", True):
            result = self.cleanup_whitespace(result)

        return result


# -----------------------------
# 사용 예시 (단위만 정규화하고 싶을 때)
# -----------------------------
# post = TextPostprocessor()
# processed = post.postprocess(
#     text_raw,
#     {"remove_fillers": False, "normalize_units": True, "cleanup_whitespace": True}
# )
