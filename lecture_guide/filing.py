"""Save a copy of the PDF under STUDY_NOTES_DIR/<Doctor or subject>/."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from . import config

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str, default: str = "Unsorted") -> str:
    s = _BAD.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80] or default


def file_copy(pdf_path: str, title: str, caption: Optional[str], base: Optional[Path] = None) -> Path:
    base = Path(base or config.STUDY_NOTES_DIR)
    first = (caption or "").strip().splitlines()[0].strip() if (caption or "").strip() else ""
    folder = base / safe_name(first or title)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (safe_name(title, "Study Guide") + ".pdf")
    shutil.copyfile(pdf_path, dest)
    return dest
