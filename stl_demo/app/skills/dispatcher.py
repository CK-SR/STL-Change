from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.config import settings
from app.models import ChangeItem, SkillExecutionResult
from app.services.asset_generation_service import AssetGenerationService
from app.services.add_fit_service import AddFitService
from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService
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
    input_path: Path | str,
    temp_output_path: Path,
    role: str,
    linked_from: Optional[str] = None,
) -> dict:
    return {
        "part_id": str(part_id),
        "input_path": str(input_path) if input_path else "",
        "temp_output_path": str(temp_output_path),
        "role": role,
        "linked_from": linked_from or "",
    }


def _normalize_add_request(change: ChangeItem) -> dict:
    params = change.params or {}
    asset_request = dict(params.get("asset_request", {}) or {})
    fit_policy = dict(params.get("fit_policy", {}) or {})
    mount_request = dict(params.get("mount_request", {}) or {})
    visual_fit = dict(params.get("visual_fit", {}) or {})
    post_transform_overrides = dict(params.get("post_transform_overrides", {}) or {})

    mount_region = (
        mount_request.get("mount_region")
        or asset_request.get("mount_region")
        or fit_policy.get("mount_region")
        or ""
    )
    if mount_region:
        mount_request.setdefault("mount_region", mount_region)

    placement_scope = mount_request.get("placement_scope")
    if not placement_scope:
        if mount_region in {"hull_side", "side", "left_side", "right_side"}:
            mount_request["placement_scope"] = settings.add_default_side_scope
        elif mount_region in {"turret_perimeter", "perimeter", "full_perimeter", "wrap"}:
            mount_request["placement_scope"] = settings.add_default_perimeter_scope
        else:
            mount_request["placement_scope"] = "single"

    visual_fit.setdefault(
        "target_ratio",
        fit_policy.get("coverage_ratio", 0.92),
    )
    visual_fit.setdefault(
        "preserve_aspect_ratio",
        settings.add_default_preserve_aspect_ratio,
    )
    visual_fit.setdefault(
        "allow_axis_stretch",
        fit_policy.get("allow_stretch", settings.add_default_allow_axis_stretch),
    )
    visual_fit.setdefault(
        "allow_unlimited_upscale",
        settings.add_default_allow_unlimited_upscale,
    )

    return {
        "attach_to": str(params.get("attach_to", "")).strip(),
        "asset_request": asset_request,
        "fit_policy": fit_policy,
        "mount_request": mount_request,
        "visual_fit": visual_fit,
        "post_transform_overrides": post_transform_overrides,
    }


def dispatch_change(
    change: ChangeItem,
    part_to_file: Dict[str, Path],
    output_dir: Path,
) -> SkillExecutionResult:
    op = change.op
    target = change.target_part

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

    if op == "add":
        add_req = _normalize_add_request(change)
        attach_to = add_req["attach_to"]
        asset_request = add_req["asset_request"]
        fit_policy = add_req["fit_policy"]
        mount_request = add_req["mount_request"]
        visual_fit = add_req["visual_fit"]
        post_transform_overrides = add_req["post_transform_overrides"]

        if not attach_to:
            return SkillExecutionResult(
                success=False,
                message="add failed: attach_to missing",
                target_part=target,
                op=op,
            )
        if attach_to not in part_to_file:
            return SkillExecutionResult(
                success=False,
                message=f"add failed: attach_to STL not found for {attach_to}",
                target_part=target,
                op=op,
            )

        asset_service = AssetGenerationService()
        asset_result = asset_service.acquire_asset_stl(
            target_part=target,
            asset_request=asset_request,
            download_dir=settings.asset_download_dir,
        )
        if not asset_result.success:
            return SkillExecutionResult(
                success=False,
                message=f"add failed during asset acquisition: {asset_result.message}",
                target_part=target,
                op=op,
                warnings=asset_result.warnings or [],
                metadata={"asset_acquisition": asset_result.to_dict()},
            )

        fit_service = AddFitService(
            anchor_service=GeometryAnchorService(),
            constraint_service=constraint_service,
        )

        temp_output = _build_temp_output_path(output_dir, target, "added_fitted")
        resolved_asset_metadata = dict(asset_result.asset_metadata or {})
        for key in ["category", "target_type", "mount_region"]:
            req_val = asset_request.get(key)
            if req_val is not None and str(req_val).strip():
                resolved_asset_metadata.setdefault(key, req_val)
                fit_policy.setdefault(key, req_val)
        if mount_request.get("mount_region"):
            resolved_asset_metadata.setdefault("mount_region", mount_request["mount_region"])

        fit_result = fit_service.fit_imported_asset(
            imported_stl_path=asset_result.local_stl_path,
            attach_to=attach_to,
            attach_to_path=part_to_file[attach_to],
            output_path=temp_output,
            asset_metadata=resolved_asset_metadata,
            fit_policy=fit_policy,
            mount_request=mount_request,
            visual_fit=visual_fit,
            post_transform_overrides=post_transform_overrides,
        )

        if not fit_result.success:
            warnings = list(asset_result.warnings or [])
            warnings.extend(fit_result.warnings)
            return SkillExecutionResult(
                success=False,
                message=f"add failed during fit: {fit_result.message}",
                target_part=target,
                op=op,
                warnings=warnings,
                metadata={
                    "asset_acquisition": asset_result.to_dict(),
                    "fit_result": fit_result.to_dict(),
                },
            )

        warnings = list(asset_result.warnings or [])
        warnings.extend(fit_result.warnings)
        return SkillExecutionResult(
            success=True,
            output_files=[fit_result.output_path],
            warnings=warnings,
            message="add success via external asset acquisition + regional local fit",
            target_part=target,
            op=op,
            metadata={
                "affected_parts": [
                    _make_affected_part_item(
                        part_id=target,
                        input_path="",
                        temp_output_path=Path(fit_result.output_path),
                        role="primary_add",
                        linked_from="",
                    )
                ],
                "attach_to": attach_to,
                "asset_acquisition": asset_result.to_dict(),
                "fit_plan": fit_result.fit_plan,
                "mount_request": mount_request,
                "visual_fit": visual_fit,
            },
        )

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
    result = SkillExecutionResult(success=False, target_part=target, op=op)

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
        result = SkillExecutionResult(success=False, message=f"constraint-only dispatch failed: {exc}")

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
