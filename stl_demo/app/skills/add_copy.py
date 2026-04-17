from __future__ import annotations

import traceback
from pathlib import Path

import numpy as np
import trimesh

from app.models import SkillExecutionResult


def add_stl_by_copy(
    source_path: Path,
    output_dir: Path,
    target_part: str,
    offset: dict,
) -> SkillExecutionResult:
    """
    复制 source_path 对应 STL，并按 offset 平移后写入 target_part 的 canonical 输出路径。
    最终输出文件名固定为：<target_part>.stl
    """
    try:
        if not source_path.exists():
            return SkillExecutionResult(
                success=False,
                message=f"add(copy) failed: file not found: {source_path}",
            )

        mesh = trimesh.load_mesh(source_path, process=False)
        if isinstance(mesh, trimesh.Scene):
            if len(mesh.geometry) == 0:
                return SkillExecutionResult(
                    success=False,
                    message=f"add(copy) failed: no geometry in scene: {source_path}",
                )
            mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

        if not isinstance(mesh, trimesh.Trimesh):
            return SkillExecutionResult(
                success=False,
                message=f"add(copy) failed: loaded object is not Trimesh: {type(mesh)}",
            )

        mesh = mesh.copy()
        mesh.vertices = mesh.vertices + np.array(
            [float(offset["x"]), float(offset["y"]), float(offset["z"])],
            dtype=float,
        )

        stem = Path(target_part).stem
        out_path = output_dir / f"{stem}.stl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out_path)

        return SkillExecutionResult(
            success=True,
            output_files=[str(out_path)],
            message="add(copy) success",
        )

    except Exception as exc:
        return SkillExecutionResult(
            success=False,
            message=f"add(copy) failed: {exc}",
            warnings=[traceback.format_exc(limit=1)],
        )