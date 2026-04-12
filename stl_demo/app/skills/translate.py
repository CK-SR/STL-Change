from __future__ import annotations

import traceback
from pathlib import Path
import numpy as np
import trimesh

from app.models import SkillExecutionResult


def translate_stl(input_path: Path, output_dir: Path, part_name: str, x: float, y: float, z: float) -> SkillExecutionResult:
    try:
        if not input_path.exists():
            return SkillExecutionResult(success=False, message=f"translate failed: file not found: {input_path}")

        mesh = trimesh.load_mesh(input_path)
        mesh.vertices = mesh.vertices + np.array([x, y, z])

        input_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(input_path)

        return SkillExecutionResult(success=True, output_files=[str(input_path)], message="translate success")
    except Exception as exc:
        return SkillExecutionResult(success=False, message=f"translate failed: {exc}", warnings=[traceback.format_exc(limit=1)])