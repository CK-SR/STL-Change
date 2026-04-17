from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.config import settings
from app.models import ChangeItem, SkillExecutionResult
from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService
from app.skills.add_copy import add_stl_by_copy
from app.skills.delete import delete_stl_file
from app.skills.transform_with_constraints import (
    TransformWithConstraints,
    transform_result_to_skill_execution,
)


def _load_constraint_service() -> PartConstraintService:
    if not settings.part_constraints_path.exists():
        raise FileNotFoundError(
            f"part_constraints.json not found: {settings.part_constraints_path}"
        )
    return PartConstraintService(settings.part_constraints_path)


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


def _build_final_output_path(output_dir: Path, part_name: str) -> Path:
    stem = Path(part_name).stem
    return output_dir / f"{stem}.stl"


def _build_temp_output_path(output_dir: Path, part_name: str, suffix: str) -> Path:
    """
    变换类操作先写入临时文件，后续由 nodes.py 统一完成：
    mesh repair -> reasonableness check -> promote to final canonical path
    """
    stem = Path(part_name).stem
    return output_dir / f".__tmp__{stem}_{suffix}.stl"


def dispatch_change(
    change: ChangeItem,
    part_to_file: Dict[str, Path],
    output_dir: Path,
) -> SkillExecutionResult:
    op = change.op
    target = change.target_part

    if op == "add":
        source_part = change.params["source_part"]
        result = add_stl_by_copy(
            source_path=part_to_file[source_part],
            output_dir=output_dir,
            target_part=target,
            offset=change.params.get("offset", {"x": 0, "y": 0, "z": 0}),
        )
        result.target_part = target
        result.op = op
        return result

    if op == "delete":
        result = delete_stl_file(part_to_file[target])
        result.target_part = target
        result.op = op
        return result

    constraint_service = _load_constraint_service()
    if target not in part_to_file:
        return SkillExecutionResult(
            success=False,
            message=f"target STL not found for {target}",
            target_part=target,
            op=op,
        )

    transformer = TransformWithConstraints(
        constraint_service=constraint_service,
        anchor_service=GeometryAnchorService(),
    )

    try:
        if op == "translate":
            p = change.params
            tr = transformer.constrained_translate(
                part_id=target,
                stl_path=part_to_file[target],
                output_path=_build_temp_output_path(output_dir, target, "translated"),
                offset_xyz_mm=[float(p["x"]), float(p["y"]), float(p["z"])],
            )
            result = transform_result_to_skill_execution(tr)

        elif op == "rotate":
            p = change.params
            tr = transformer.anchored_rotate(
                part_id=target,
                stl_path=part_to_file[target],
                output_path=_build_temp_output_path(output_dir, target, "rotated"),
                angle_deg=float(p["degrees"]),
                axis=_safe_axis_vector_from_params(p),
            )
            result = transform_result_to_skill_execution(tr)

        elif op == "stretch":
            p = change.params
            tr = transformer.constrained_stretch(
                part_id=target,
                stl_path=part_to_file[target],
                output_path=_build_temp_output_path(output_dir, target, "stretched"),
                delta_mm=float(p["delta_mm"]),
                axis=_safe_axis_vector_from_params(p),
            )
            result = transform_result_to_skill_execution(tr)

        elif op == "scale":
            p = change.params
            if "delta_mm" not in p:
                result = SkillExecutionResult(
                    success=False,
                    message="uniform scale is disabled; use stretch or scale.delta_mm instead",
                )
            else:
                tr = transformer.constrained_stretch(
                    part_id=target,
                    stl_path=part_to_file[target],
                    output_path=_build_temp_output_path(output_dir, target, "stretched"),
                    delta_mm=float(p["delta_mm"]),
                    axis=_safe_axis_vector_from_params(p),
                )
                result = transform_result_to_skill_execution(tr)

        else:
            result = SkillExecutionResult(
                success=False,
                message=f"unsupported op: {op}",
            )

    except Exception as exc:
        result = SkillExecutionResult(
            success=False,
            message=f"constraint-only dispatch failed: {exc}",
        )

    result.target_part = target
    result.op = op
    return result