from __future__ import annotations

import math
import traceback
from pathlib import Path
import trimesh
import trimesh.transformations as tf

from app.models import SkillExecutionResult


AXIS_MAP = {
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
}


def rotate_stl(input_path: Path, output_dir: Path, part_name: str, axis: str, degrees: float) -> SkillExecutionResult:
    try:
        if not input_path.exists():
            return SkillExecutionResult(success=False, message=f"rotate failed: file not found: {input_path}")

        mesh = trimesh.load_mesh(input_path)
        center = mesh.centroid
        matrix = tf.rotation_matrix(math.radians(degrees), AXIS_MAP[axis], point=center)
        mesh.apply_transform(matrix)

        input_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(input_path)

        return SkillExecutionResult(success=True, output_files=[str(input_path)], message="rotate success")
    except Exception as exc:
        return SkillExecutionResult(success=False, message=f"rotate failed: {exc}", warnings=[traceback.format_exc(limit=1)])