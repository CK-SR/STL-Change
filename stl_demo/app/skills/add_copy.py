from __future__ import annotations

import traceback
from pathlib import Path
import numpy as np
import trimesh

from app.models import SkillExecutionResult


def add_stl_by_copy(
    source_path: Path,
    output_dir: Path,
    source_part: str,
    offset: dict,
) -> SkillExecutionResult:
    try:
        if not source_path.exists():
            return SkillExecutionResult(success=False, message=f"add(copy) failed: file not found: {source_path}")

        mesh = trimesh.load_mesh(source_path)
        mesh.vertices = mesh.vertices + np.array([offset["x"], offset["y"], offset["z"]])

        stem = Path(source_part).stem
        out_name = f"{stem}_added_001.stl"
        out_path = output_dir / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out_path)

        return SkillExecutionResult(success=True, output_files=[str(out_path)], message="add(copy) success")
    except Exception as exc:
        return SkillExecutionResult(success=False, message=f"add(copy) failed: {exc}", warnings=[traceback.format_exc(limit=1)])