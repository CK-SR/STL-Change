from __future__ import annotations

import shutil
from pathlib import Path
from typing import List


def prepare_full_stl_bundle(src_dir: Path, dst_dir: Path) -> List[str]:
    dst_dir.mkdir(parents=True, exist_ok=True)

    copied: List[str] = []
    for src in sorted(src_dir.glob("*.stl")):
        dst = dst_dir / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))

    return copied