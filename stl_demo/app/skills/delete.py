from __future__ import annotations

from pathlib import Path
from app.models import SkillExecutionResult


def delete_stl_file(part_path: Path) -> SkillExecutionResult:
    if not part_path.exists():
        return SkillExecutionResult(
            success=False,
            output_files=[],
            message=f"delete failed: file not found: {part_path}",
        )

    part_path.unlink()
    return SkillExecutionResult(
        success=True,
        output_files=[],
        message=f"{part_path.name} 已删除",
    )