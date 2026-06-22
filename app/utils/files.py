from __future__ import annotations

import os
import re
from pathlib import Path


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    """
    Produce a safe filename for local storage (does not preserve directories).
    """

    base = os.path.basename(filename).strip()
    base = base.replace(" ", "_")
    base = _FILENAME_SAFE_RE.sub("-", base)
    return base[:255] if base else "file"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

