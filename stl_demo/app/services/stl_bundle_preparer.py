from __future__ import annotations

import shutil
from pathlib import Path
from typing import List


def prepare_full_stl_bundle(src_dir: Path, dst_dir: Path) -> List[str]:
    """
    将输入 STL 目录完整复制到最终输出目录。
    与旧版不同：
    1. 每次运行前先清空 dst_dir，避免历史残留文件污染当前结果；
    2. dst_dir 语义固定为“本次运行的最终快照目录”。
    """
    if dst_dir.exists():
        shutil.rmtree(dst_dir)

    dst_dir.mkdir(parents=True, exist_ok=True)

    copied: List[str] = []
    for src in sorted(src_dir.glob("*.stl")):
        dst = dst_dir / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))

    return copied