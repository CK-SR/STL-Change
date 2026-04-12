from __future__ import annotations

from pathlib import Path
from app.models import SkillExecutionResult


class BaseSkill:
    def run(self, *args, **kwargs) -> SkillExecutionResult:
        raise NotImplementedError


def resolve_output_part_path(output_dir: Path, part_name: str) -> Path:
    name = Path(part_name).name
    if not name.endswith(".stl"):
        name = f"{name}.stl"
    return output_dir / name