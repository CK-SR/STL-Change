from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.config import settings
from app.models import ChangeItem, SkillExecutionResult
from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService
from app.skills.add_copy import add_stl_by_copy
from app.skills.delete import delete_stl_file
from app.skills.rotate import rotate_stl
from app.skills.scale import scale_stl
from app.skills.translate import translate_stl
from app.skills.transform_with_constraints import (
    TransformWithConstraints,
    transform_result_to_skill_execution,
)


def _load_constraint_service_if_available() -> Optional[PartConstraintService]:
    if not settings.part_constraints_path.exists():
        return None
    try:
        return PartConstraintService(settings.part_constraints_path)
    except Exception:
        return None


def _safe_axis_vector_from_params(params: dict) -> Optional[list[float]]:
    axis_vector = params.get("axis_vector")
    if isinstance(axis_vector, list) and len(axis_vector) == 3:
        try:
            return [float(x) for x in axis_vector]
        except Exception:
            return None

    axis_name = params.get("axis")
    if axis_name in {"x", "y", "z"}:
        gas = GeometryAnchorService()
        return gas.axis_name_to_vector(str(axis_name)).tolist()

    return None


def _build_output_path(output_dir: Path, part_name: str, suffix: str) -> Path:
    stem = Path(part_name).stem
    return output_dir / f"{stem}_{suffix}.stl"


def dispatch_change(
    change: ChangeItem,
    part_to_file: Dict[str, Path],
    output_dir: Path,
) -> SkillExecutionResult:
    op = change.op
    target = change.target_part
    constraint_service = _load_constraint_service_if_available()

    if op == "delete":
        result = delete_stl_file(part_to_file[target])

    elif op == "add":
        source_part = change.params["source_part"]
        result = add_stl_by_copy(
            part_to_file[source_part],
            output_dir,
            source_part,
            change.params.get("offset", {"x": 0, "y": 0, "z": 0}),
        )

    elif op in {"translate", "rotate", "stretch", "scale"} and constraint_service is not None and target in part_to_file:
        transformer = TransformWithConstraints(
            constraint_service=constraint_service,
            anchor_service=GeometryAnchorService(),
        )

        try:
            has_constraint = constraint_service.get_part_constraint(target) is not None

            if has_constraint and op == "translate":
                p = change.params
                tr = transformer.constrained_translate(
                    part_id=target,
                    stl_path=part_to_file[target],
                    output_path=_build_output_path(output_dir, target, "translated"),
                    offset_xyz_mm=[float(p["x"]), float(p["y"]), float(p["z"])],
                )
                result = transform_result_to_skill_execution(tr)

            elif has_constraint and op == "rotate":
                p = change.params
                tr = transformer.anchored_rotate(
                    part_id=target,
                    stl_path=part_to_file[target],
                    output_path=_build_output_path(output_dir, target, "rotated"),
                    angle_deg=float(p["degrees"]),
                    axis=_safe_axis_vector_from_params(p),
                )
                result = transform_result_to_skill_execution(tr)

            elif has_constraint and op == "stretch":
                p = change.params
                tr = transformer.constrained_stretch(
                    part_id=target,
                    stl_path=part_to_file[target],
                    output_path=_build_output_path(output_dir, target, "stretched"),
                    delta_mm=float(p["delta_mm"]),
                    axis=_safe_axis_vector_from_params(p),
                )
                result = transform_result_to_skill_execution(tr)

            elif has_constraint and op == "scale" and "delta_mm" in change.params:
                p = change.params
                tr = transformer.constrained_stretch(
                    part_id=target,
                    stl_path=part_to_file[target],
                    output_path=_build_output_path(output_dir, target, "stretched"),
                    delta_mm=float(p["delta_mm"]),
                    axis=_safe_axis_vector_from_params(p),
                )
                result = transform_result_to_skill_execution(tr)

            elif op == "scale":
                p = change.params
                result = scale_stl(
                    part_to_file[target],
                    output_dir,
                    target,
                    float(p["x"]),
                    float(p["y"]),
                    float(p["z"]),
                )

            elif op == "translate":
                p = change.params
                result = translate_stl(
                    part_to_file[target],
                    output_dir,
                    target,
                    float(p["x"]),
                    float(p["y"]),
                    float(p["z"]),
                )

            elif op == "rotate":
                p = change.params
                result = rotate_stl(
                    part_to_file[target],
                    output_dir,
                    target,
                    str(p["axis"]),
                    float(p["degrees"]),
                )

            else:
                result = SkillExecutionResult(success=False, message=f"unsupported op: {op}")

        except Exception as exc:
            result = SkillExecutionResult(
                success=False,
                message=f"constraint-aware dispatch failed: {exc}",
            )

    elif op == "scale":
        p = change.params
        result = scale_stl(
            part_to_file[target],
            output_dir,
            target,
            float(p["x"]),
            float(p["y"]),
            float(p["z"]),
        )

    elif op == "translate":
        p = change.params
        result = translate_stl(
            part_to_file[target],
            output_dir,
            target,
            float(p["x"]),
            float(p["y"]),
            float(p["z"]),
        )

    elif op == "rotate":
        p = change.params
        result = rotate_stl(
            part_to_file[target],
            output_dir,
            target,
            str(p["axis"]),
            float(p["degrees"]),
        )

    elif op == "stretch":
        result = SkillExecutionResult(
            success=False,
            message="stretch op requires part_constraints.json and target part constraint",
        )

    else:
        result = SkillExecutionResult(success=False, message=f"unsupported op: {op}")

    result.target_part = target
    result.op = op
    return result