from __future__ import annotations

import math
import traceback
from pathlib import Path
import trimesh
import trimesh.transformations as tf

from app.models import SkillExecutionResult
from app.skills.base import out_file_path


AXIS_MAP = {
    "x": [1.0, 0.0, 0.0],
    "y": [0.0, 1.0, 0.0],
    "z": [0.0, 0.0, 1.0],
}


def rotate_stl(input_path: Path, output_dir: Path, part_name: str, axis: str, degrees: float) -> SkillExecutionResult:
    try:
        mesh = trimesh.load_mesh(input_path)
        center = mesh.centroid
        matrix = tf.rotation_matrix(math.radians(degrees), AXIS_MAP[axis], point=center)
        mesh.apply_transform(matrix)
        out_path = out_file_path(output_dir, part_name, "_rotated")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out_path)
        return SkillExecutionResult(success=True, output_files=[str(out_path)], message="rotate success")
    except Exception as exc:
        return SkillExecutionResult(success=False, message=f"rotate failed: {exc}", warnings=[traceback.format_exc(limit=1)])
