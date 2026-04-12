from __future__ import annotations

import traceback
from pathlib import Path
import numpy as np
import trimesh

from app.models import SkillExecutionResult


def scale_stl(input_path: Path, output_dir: Path, part_name: str, x: float, y: float, z: float) -> SkillExecutionResult:
    try:
        if not input_path.exists():
            return SkillExecutionResult(success=False, message=f"scale failed: file not found: {input_path}")

        mesh = trimesh.load_mesh(input_path)
        center = mesh.centroid
        mesh.vertices = (mesh.vertices - center) * np.array([x, y, z]) + center

        input_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(input_path)

        return SkillExecutionResult(success=True, output_files=[str(input_path)], message="scale success")
    except Exception as exc:
        return SkillExecutionResult(success=False, message=f"scale failed: {exc}", warnings=[traceback.format_exc(limit=1)])