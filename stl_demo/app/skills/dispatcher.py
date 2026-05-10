from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

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
    """Return a run-local temporary STL path outside the final snapshot directory."""
    stem = Path(part_name).stem
    temp_dir = settings.temp_stl_dir

    try:
        is_final_snapshot_dir = output_dir.resolve() == settings.final_stl_dir.resolve()
    except FileNotFoundError:
        is_final_snapshot_dir = output_dir == settings.final_stl_dir

    if not is_final_snapshot_dir:
        temp_dir = output_dir.parent / "tmp_stl"

    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"__tmp__{stem}_{suffix}.stl"


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


def _safe_join_text(parts: list[str]) -> str:
    merged: list[str] = []
    seen: set[str] = set()

    for item in parts:
        text = str(item or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        merged.append(text)

    return "；".join(merged)


def _format_function_names(names: list[str]) -> str:
    cleaned = [str(x).strip() for x in names if str(x).strip()]
    return "、".join(cleaned)


def _format_size_hint(extents: list[float] | list[int] | None) -> str:
    if not extents or len(extents) != 3:
        return ""
    try:
        x, y, z = [float(v) for v in extents]
        return f"父件尺寸约为 {x:.1f}×{y:.1f}×{z:.1f} mm"
    except Exception:
        return ""


def _build_rich_asset_request_content(
    *,
    change: ChangeItem,
    attach_to: str,
    asset_request: dict,
    mount_request: dict,
    constraint_service: PartConstraintService,
) -> str:
    base_content = str(asset_request.get("content", "")).strip()
    category = str(asset_request.get("category", "")).strip()
    target_type = str(asset_request.get("target_type", "")).strip()
    mount_region = str(
        mount_request.get("mount_region")
        or asset_request.get("mount_region")
        or ""
    ).strip()
    placement_scope = str(mount_request.get("placement_scope", "")).strip()
    preferred_strategy = str(mount_request.get("preferred_strategy", "")).strip()
    reason = str(change.reason or "").strip()

    parent_part_name = ""
    parent_edit_type = ""
    parent_desc = ""
    parent_functions = ""
    parent_size_hint = ""

    try:
        parent_constraint = constraint_service.get_part_constraint(attach_to)
        if parent_constraint is not None:
            parent_part_name = str(parent_constraint.part_name or "").strip()
            parent_edit_type = str(parent_constraint.edit_type or "").strip()
            parent_desc = str(parent_constraint.semantic_note or "").strip()
            parent_functions = _format_function_names(parent_constraint.function_names)
            parent_size_hint = _format_size_hint(parent_constraint.geometry.aabb_extents)
    except Exception:
        pass

    parent_ref = attach_to
    if parent_part_name and parent_part_name != attach_to:
        parent_ref = f"{attach_to}（{parent_part_name}）"

    rich_content = _safe_join_text(
        [
            f"目标新增件标识：{change.target_part}" if str(change.target_part).strip() else "",
            f"新增件基础检索词：{base_content}" if base_content else "",
            f"原始需求：{reason}" if reason else "",
            f"挂载父件：{parent_ref}" if parent_ref else "",
            f"父件类型：{parent_edit_type}" if parent_edit_type else "",
            f"父件功能：{parent_functions}" if parent_functions else "",
            f"父件描述：{parent_desc}" if parent_desc else "",
            parent_size_hint,
            f"安装区域：{mount_region}" if mount_region else "",
            f"布置范围：{placement_scope}" if placement_scope else "",
            f"装配策略：{preferred_strategy}" if preferred_strategy else "",
            f"素材类别偏好：{category}" if category else "",
            f"目标平台：{target_type}" if target_type else "",
            "请优先匹配与上述结构特征、用途和安装区域一致的 STL 素材，而不是仅按部件名称做模糊匹配。",
        ]
    )

    return rich_content or base_content



def _build_resolved_asset_metadata(
    *,
    asset_metadata: dict,
    asset_request: dict,
    mount_request: dict,
    fit_policy: dict,
) -> dict:
    resolved_asset_metadata = dict(asset_metadata or {})
    for key in ["category", "target_type", "mount_region", "placement_scope", "preferred_strategy"]:
        req_val = asset_request.get(key)
        if req_val is not None and str(req_val).strip():
            resolved_asset_metadata.setdefault(key, req_val)
            fit_policy.setdefault(key, req_val)
    if mount_request.get("mount_region"):
        resolved_asset_metadata.setdefault("mount_region", mount_request["mount_region"])
    if mount_request.get("placement_scope"):
        resolved_asset_metadata.setdefault("placement_scope", mount_request["placement_scope"])
    if mount_request.get("preferred_strategy"):
        resolved_asset_metadata.setdefault("preferred_strategy", mount_request["preferred_strategy"])
    return resolved_asset_metadata


def _extract_selected_pose_score(fit_plan: dict) -> float:
    best_score = 0.0
    for surface_report in fit_plan.get("surface_reports", []) or []:
        if not isinstance(surface_report, dict):
            continue
        pose_selection = surface_report.get("pose_selection") or {}
        if not isinstance(pose_selection, dict):
            continue
        selected_id = str(pose_selection.get("selected_candidate_id", "")).strip()
        for item in pose_selection.get("scores", []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("candidate_id", "")).strip() != selected_id:
                continue
            try:
                best_score += float(item.get("score", 0.0))
            except (TypeError, ValueError):
                best_score += 0.0
            break
    return best_score

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

        asset_request = dict(asset_request)
        asset_request.setdefault("input_type", "text")
        asset_request.setdefault("mount_region", mount_request.get("mount_region", ""))
        asset_request.setdefault("placement_scope", mount_request.get("placement_scope", ""))
        asset_request.setdefault("preferred_strategy", mount_request.get("preferred_strategy", ""))

        fit_service = AddFitService(
            anchor_service=GeometryAnchorService(),
            constraint_service=constraint_service,
        )

        preliminary_surface_plan = fit_service.surface_service.plan_mount_surfaces(
            attach_to=attach_to,
            attach_to_path=part_to_file[attach_to],
            mount_region=str(mount_request.get("mount_region") or asset_request.get("mount_region") or ""),
            placement_scope=str(mount_request.get("placement_scope") or asset_request.get("placement_scope") or ""),
            preferred_strategy=str(mount_request.get("preferred_strategy") or asset_request.get("preferred_strategy") or ""),
            category=str(asset_request.get("category") or fit_policy.get("category") or ""),
        )
        if preliminary_surface_plan.mount_strategy != "top_cover":
            return SkillExecutionResult(
                success=False,
                message=(
                    f"add skipped before asset acquisition: unsupported mount strategy "
                    f"{preliminary_surface_plan.mount_strategy}; only top_cover is enabled"
                ),
                target_part=target,
                op=op,
                metadata={
                    "asset_request_skipped": True,
                    "skip_reason": "unsupported_mount_strategy",
                    "surface_plan": preliminary_surface_plan.to_dict(),
                    "supported_mount_strategies": ["top_cover"],
                    "mount_request": mount_request,
                    "asset_request_used": asset_request,
                },
            )

        asset_request["content"] = _build_rich_asset_request_content(
            change=change,
            attach_to=attach_to,
            asset_request=asset_request,
            mount_request=mount_request,
            constraint_service=constraint_service,
        )
        asset_request["topk"] = 5

        asset_service = AssetGenerationService()
        asset_result = asset_service.acquire_asset_stl_candidates(
            target_part=target,
            asset_request=asset_request,
            download_dir=settings.asset_download_dir,
            max_assets=5,
        )
        if not asset_result.success:
            return SkillExecutionResult(
                success=False,
                message=f"add failed during asset acquisition: {asset_result.message}",
                target_part=target,
                op=op,
                warnings=asset_result.warnings or [],
                metadata={
                    "asset_acquisition": asset_result.to_dict(),
                    "asset_request_used": asset_request,
                },
            )

        candidate_assets = list(asset_result.candidate_assets or [])
        if not candidate_assets and asset_result.local_stl_path:
            candidate_assets = [
                {
                    "rank": 1,
                    "local_stl_path": asset_result.local_stl_path,
                    "download_url": asset_result.download_url,
                    "asset_metadata": asset_result.asset_metadata or {},
                }
            ]

        candidate_attempts: list[dict[str, Any]] = []
        best_fit_result = None
        best_candidate_asset: dict[str, Any] | None = None
        best_score = -1.0

        for idx, candidate_asset in enumerate(candidate_assets[:5], start=1):
            candidate_fit_policy = dict(fit_policy)
            resolved_asset_metadata = _build_resolved_asset_metadata(
                asset_metadata=dict(candidate_asset.get("asset_metadata") or {}),
                asset_request=asset_request,
                mount_request=mount_request,
                fit_policy=candidate_fit_policy,
            )
            temp_output = _build_temp_output_path(output_dir, target, f"added_fitted_candidate_{idx}")
            fit_result = fit_service.fit_imported_asset(
                imported_stl_path=str(candidate_asset.get("local_stl_path", "")),
                attach_to=attach_to,
                attach_to_path=part_to_file[attach_to],
                output_path=temp_output,
                asset_metadata=resolved_asset_metadata,
                fit_policy=candidate_fit_policy,
                mount_request=mount_request,
                visual_fit=visual_fit,
                post_transform_overrides=post_transform_overrides,
            )
            pose_score = _extract_selected_pose_score(fit_result.fit_plan) if fit_result.success else 0.0
            candidate_attempts.append(
                {
                    "candidate_asset": candidate_asset,
                    "fit_result": fit_result.to_dict(),
                    "selected_pose_score": pose_score,
                }
            )

            if fit_result.success and pose_score > best_score:
                best_score = pose_score
                best_fit_result = fit_result
                best_candidate_asset = candidate_asset

        if best_fit_result is None or best_candidate_asset is None:
            warnings = list(asset_result.warnings or [])
            for attempt in candidate_attempts:
                fit_result_data = attempt.get("fit_result") or {}
                warnings.extend(fit_result_data.get("warnings") or [])
            return SkillExecutionResult(
                success=False,
                message="add failed during fit: all candidate assets failed visual pose fit",
                target_part=target,
                op=op,
                warnings=warnings,
                metadata={
                    "asset_acquisition": asset_result.to_dict(),
                    "candidate_fit_attempts": candidate_attempts,
                    "asset_request_used": asset_request,
                },
            )

        warnings = list(asset_result.warnings or [])
        warnings.extend(best_fit_result.warnings)
        return SkillExecutionResult(
            success=True,
            output_files=[best_fit_result.output_path],
            warnings=warnings,
            message="add success via top5 asset candidates + vision-ranked pose fit",
            target_part=target,
            op=op,
            metadata={
                "affected_parts": [
                    _make_affected_part_item(
                        part_id=target,
                        input_path="",
                        temp_output_path=Path(best_fit_result.output_path),
                        role="primary_add",
                        linked_from="",
                    )
                ],
                "attach_to": attach_to,
                "asset_request_used": asset_request,
                "asset_acquisition": asset_result.to_dict(),
                "candidate_fit_attempts": candidate_attempts,
                "selected_asset_candidate": best_candidate_asset,
                "selected_pose_score": best_score,
                "fit_plan": best_fit_result.fit_plan,
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