from __future__ import annotations

import re
from typing import List


_WORD_RE = re.compile(r"[\w가-힣]+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    """Lightweight tokenizer.

    - Lowercases Latin text.
    - Keeps Korean syllables.
    - Splits on non-word characters.

    Note: This is intentionally simple for benchmark harness use.
    """
    if not text:
        return []
    # Lowercase only affects Latin characters
    t = text.lower()
    return _WORD_RE.findall(t)
