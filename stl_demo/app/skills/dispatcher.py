from __future__ import annotations

from pathlib import Path
from typing import Dict

from app.models import ChangeItem, SkillExecutionResult
from app.skills.add_copy import add_stl_by_copy
from app.skills.delete import delete_stl_file
from app.skills.rotate import rotate_stl
from app.skills.scale import scale_stl
from app.skills.translate import translate_stl


def dispatch_change(
    change: ChangeItem,
    part_to_file: Dict[str, Path],
    output_dir: Path,
) -> SkillExecutionResult:
    op = change.op
    target = change.target_part

    if op == "delete":
        result = delete_stl_file(part_to_file[target])

    elif op == "add":
        source_part = change.params["source_part"]
        result = add_stl_by_copy(part_to_file[source_part], output_dir, source_part, change.params["offset"])

    elif op == "scale":
        p = change.params
        result = scale_stl(part_to_file[target], output_dir, target, float(p["x"]), float(p["y"]), float(p["z"]))

    elif op == "translate":
        p = change.params
        result = translate_stl(part_to_file[target], output_dir, target, float(p["x"]), float(p["y"]), float(p["z"]))

    elif op == "rotate":
        p = change.params
        result = rotate_stl(part_to_file[target], output_dir, target, str(p["axis"]), float(p["degrees"]))

    else:
        result = SkillExecutionResult(success=False, message=f"unsupported op: {op}")

    result.target_part = target
    result.op = op
    return result