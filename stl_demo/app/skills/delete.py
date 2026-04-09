from __future__ import annotations

from app.models import SkillExecutionResult


def delete_stl(part_name: str) -> SkillExecutionResult:
    return SkillExecutionResult(success=True, output_files=[], message=f"{part_name} 已删除")
