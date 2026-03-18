"""Atomic file writes — write to temp, then rename.

If the process crashes mid-write, the original file is untouched.
os.rename() is atomic on POSIX when source and dest are on the same filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.rename(str(tmp), str(path))
    except Exception:
        # Clean up temp file on failure
        if tmp.exists():
            tmp.unlink()
        raise
