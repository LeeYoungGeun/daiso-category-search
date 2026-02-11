from __future__ import annotations

from pathlib import Path
import hashlib


def file_sha256(path: Path) -> str:
    """Return sha256 hex digest of a file (streaming, memory-safe)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_catalog_meta(catalog_path: str, n_rows: int) -> dict:
    """Build reproducibility metadata for the catalog used in a run."""
    p = Path(catalog_path)
    return {
        "catalog_path": str(p),
        "catalog_n_rows": int(n_rows),
        "catalog_sha256": file_sha256(p) if p.exists() else None,
    }
