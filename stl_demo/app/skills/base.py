from __future__ import annotations

from pathlib import Path
from app.models import SkillExecutionResult


class BaseSkill:
    def run(self, *args, **kwargs) -> SkillExecutionResult:
        raise NotImplementedError


def out_file_path(output_dir: Path, part_name: str, suffix: str = "") -> Path:
    stem = Path(part_name).stem
    name = f"{stem}{suffix}.stl"
    return output_dir / name
