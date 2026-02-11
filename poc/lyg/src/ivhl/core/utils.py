from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict


def now_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def ensure_dir(p: str) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def copy_if_exists(src: str, dst_dir: str) -> str:
    sp = Path(src)
    if not sp.exists():
        return ""
    dp = Path(dst_dir) / sp.name
    dp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sp, dp)
    return str(dp)


def env_or_blank(key: str) -> str:
    return os.getenv(key, "")
