from __future__ import annotations

import traceback
from pathlib import Path
import numpy as np
import trimesh

from app.models import SkillExecutionResult
from app.skills.base import out_file_path


def translate_stl(input_path: Path, output_dir: Path, part_name: str, x: float, y: float, z: float) -> SkillExecutionResult:
    try:
        mesh = trimesh.load_mesh(input_path)
        mesh.vertices = mesh.vertices + np.array([x, y, z])
        out_path = out_file_path(output_dir, part_name, "_translated")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(out_path)
        return SkillExecutionResult(success=True, output_files=[str(out_path)], message="translate success")
    except Exception as exc:
        return SkillExecutionResult(success=False, message=f"translate failed: {exc}", warnings=[traceback.format_exc(limit=1)])
