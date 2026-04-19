from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.config import settings
from app.models import ChangeItem, SkillExecutionResult
from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService
from app.skills.add_copy import add_stl_by_copy
from app.skills.delete import delete_stl_file
from app.skills.rigid_follow import apply_rigid_transform
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


def _build_temp_output_path(output_dir: Path, part_name: str, suffix: str) -> Path:
    stem = Path(part_name).stem
    return output_dir / f".__tmp__{stem}_{suffix}.stl"


def _make_affected_part_item(
    *,
    part_id: str,
    input_path: Path,
    temp_output_path: Path,
    role: str,
    linked_from: Optional[str] = None,
) -> dict:
    return {
        "part_id": part_id,
        "input_path": str(input_path),
        "temp_output_path": str(temp_output_path),
        "role": role,
        "linked_from": linked_from or "",
    }


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
        result.metadata = {
            "affected_parts": [
                {
                    "part_id": target,
                    "input_path": "",
                    "temp_output_path": result.output_files[0] if result.output_files else "",
                    "role": "primary_add",
                    "linked_from": "",
                }
            ]
        }
        return result

    if op == "delete":
        result = delete_stl_file(part_to_file[target])
        result.target_part = target
        result.op = op
        result.metadata = {
            "affected_parts": [
                {
                    "part_id": target,
                    "input_path": str(part_to_file[target]),
                    "temp_output_path": "",
                    "role": "primary_delete",
                    "linked_from": "",
                }
            ]
        }
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

    result = SkillExecutionResult(
        success=False,
        target_part=target,
        op=op,
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
            result = SkillExecutionResult(success=False, message=f"unsupported op: {op}")

    except Exception as exc:
        result = SkillExecutionResult(
            success=False,
            message=f"constraint-only dispatch failed: {exc}",
        )

    result.target_part = target
    result.op = op

    if not result.success:
        return result

    primary_temp_output = Path(result.output_files[0])
    primary_input_path = part_to_file[target]

    affected_parts = [
        _make_affected_part_item(
            part_id=target,
            input_path=primary_input_path,
            temp_output_path=primary_temp_output,
            role="primary",
        )
    ]

    # 联动：仅对刚体操作 cascade
    transform_matrix = result.metadata.get("transform_matrix") if result.metadata else None
    if op in {"rotate", "translate"} and transform_matrix:
        linked_children = constraint_service.list_linked_children(target, op_name=op)

        for child_id in linked_children:
            if child_id not in part_to_file:
                result.warnings.append(f"linked_child_missing={child_id}")
                continue

            child_input_path = part_to_file[child_id]
            child_temp_output = _build_temp_output_path(output_dir, child_id, f"follow_{op}")

            try:
                apply_rigid_transform(
                    part_id=child_id,
                    stl_path=child_input_path,
                    output_path=child_temp_output,
                    transform_matrix=transform_matrix,
                )
                affected_parts.append(
                    _make_affected_part_item(
                        part_id=child_id,
                        input_path=child_input_path,
                        temp_output_path=child_temp_output,
                        role="linked_follow",
                        linked_from=target,
                    )
                )
                result.warnings.append(f"linked_follow_applied={child_id}")
            except Exception as exc:
                result.warnings.append(f"linked_follow_failed={child_id}:{exc}")

    result.metadata["affected_parts"] = affected_parts
    return result