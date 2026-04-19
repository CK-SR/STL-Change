from __future__ import annotations

from typing import Dict, List

from app.models import ChangeIntent, ValidationResult


ALLOWED_OPS = {"scale", "translate", "rotate", "delete", "add", "stretch"}


def _coerce_float(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _coerce_bool(value: object) -> bool:
    return isinstance(value, bool)


def _validate_xyz_dict(errors: List[str], params: Dict[str, object], prefix: str = "") -> None:
    for axis in ["x", "y", "z"]:
        key = f"{prefix}{axis}"
        if axis not in params:
            errors.append(f"缺少参数 {key}")
        elif not _coerce_float(params.get(axis)):
            errors.append(f"参数 {key} 不是数值")


def _constraint_map(part_constraints: List[dict]) -> Dict[str, dict]:
    mapping: Dict[str, dict] = {}
    for item in part_constraints:
        pid = str(item.get("part_id", "")).strip()
        pname = str(item.get("part_name", "")).strip()
        if pid:
            mapping[pid] = item
        if pname:
            mapping[pname] = item
    return mapping


def validate_change_intent(
    intent: ChangeIntent,
    existing_parts: set[str],
    part_constraints: List[dict] | None = None,
) -> List[ValidationResult]:
    results: List[ValidationResult] = []
    constraints_map = _constraint_map(part_constraints or [])

    for i, change in enumerate(intent.changes):
        errors: List[str] = []

        if change.op not in ALLOWED_OPS:
            errors.append("op 不在允许列表")

        if not isinstance(change.params, Dict):
            errors.append("params 必须为 dict")

        p = change.params if isinstance(change.params, Dict) else {}

        if change.op != "add" and change.target_part not in existing_parts:
            errors.append("target_part 不存在")

        if change.op == "translate":
            _validate_xyz_dict(errors, p)

        elif change.op == "rotate":
            axis_value = p.get("axis")
            axis_vector = p.get("axis_vector")
            axis_valid = axis_value in {"x", "y", "z"} or (
                isinstance(axis_vector, list)
                and len(axis_vector) == 3
                and all(_coerce_float(x) for x in axis_vector)
            )
            if not axis_valid:
                errors.append("rotate.axis 必须是 x/y/z，或提供 axis_vector=[x,y,z]")
            if not _coerce_float(p.get("degrees")):
                errors.append("rotate.degrees 必须是数值")

        elif change.op == "scale":
            if "delta_mm" not in p:
                errors.append("uniform scale 已关闭，请改用 stretch 或 scale.delta_mm")
            elif not _coerce_float(p.get("delta_mm")):
                errors.append("scale.delta_mm 必须是数值")

        elif change.op == "stretch":
            if not _coerce_float(p.get("delta_mm")):
                errors.append("stretch.delta_mm 必须是数值")
            axis_vector = p.get("axis_vector")
            if axis_vector is not None:
                if not (
                    isinstance(axis_vector, list)
                    and len(axis_vector) == 3
                    and all(_coerce_float(x) for x in axis_vector)
                ):
                    errors.append("stretch.axis_vector 必须是长度为 3 的数值数组")

        elif change.op == "add":
            if change.target_part in existing_parts:
                errors.append("add.target_part 已存在，不能覆盖已有部件")

            attach_to = str(p.get("attach_to", "")).strip()
            if not attach_to:
                errors.append("add.attach_to 缺失")
            elif attach_to not in existing_parts:
                errors.append("add.attach_to 不存在")

            asset_request = p.get("asset_request")
            if not isinstance(asset_request, dict):
                errors.append("add.asset_request 必须是 dict")
            else:
                content = str(asset_request.get("content", "")).strip()
                if not content:
                    errors.append("add.asset_request.content 不能为空")

                input_type = asset_request.get("input_type")
                if input_type is not None and input_type not in {"text", "image"}:
                    errors.append("add.asset_request.input_type 只能是 text/image/null")

                for name in [
                    "auto_approve",
                    "auto_accept_prompt",
                    "auto_accept_generation",
                    "force_generate",
                ]:
                    value = asset_request.get(name)
                    if value is not None and not _coerce_bool(value):
                        errors.append(f"add.asset_request.{name} 必须是 bool")

                topk = asset_request.get("topk")
                if topk is not None:
                    try:
                        if int(topk) <= 0:
                            errors.append("add.asset_request.topk 必须 > 0")
                    except Exception:
                        errors.append("add.asset_request.topk 必须是整数")

            fit_policy = p.get("fit_policy")
            if fit_policy is not None:
                if not isinstance(fit_policy, dict):
                    errors.append("add.fit_policy 必须是 dict")
                else:
                    if fit_policy.get("coverage_ratio") is not None and not _coerce_float(
                        fit_policy.get("coverage_ratio")
                    ):
                        errors.append("add.fit_policy.coverage_ratio 必须是数值")
                    if fit_policy.get("clearance_mm") is not None and not _coerce_float(
                        fit_policy.get("clearance_mm")
                    ):
                        errors.append("add.fit_policy.clearance_mm 必须是数值")
                    if fit_policy.get("allow_stretch") is not None and not _coerce_bool(
                        fit_policy.get("allow_stretch")
                    ):
                        errors.append("add.fit_policy.allow_stretch 必须是 bool")

            overrides = p.get("post_transform_overrides")
            if overrides is not None:
                if not isinstance(overrides, dict):
                    errors.append("add.post_transform_overrides 必须是 dict")
                else:
                    translate = overrides.get("translate")
                    if translate is not None:
                        if not isinstance(translate, dict):
                            errors.append("add.post_transform_overrides.translate 必须是 dict")
                        else:
                            _validate_xyz_dict(
                                errors,
                                translate,
                                prefix="add.post_transform_overrides.translate.",
                            )

                    rotate = overrides.get("rotate")
                    if rotate is not None:
                        if not isinstance(rotate, dict):
                            errors.append("add.post_transform_overrides.rotate 必须是 dict")
                        else:
                            axis_value = rotate.get("axis")
                            if axis_value not in {"x", "y", "z"}:
                                errors.append(
                                    "add.post_transform_overrides.rotate.axis 必须是 x/y/z"
                                )
                            if not _coerce_float(rotate.get("degrees")):
                                errors.append(
                                    "add.post_transform_overrides.rotate.degrees 必须是数值"
                                )

                    stretch = overrides.get("stretch")
                    if stretch is not None:
                        if not isinstance(stretch, dict):
                            errors.append("add.post_transform_overrides.stretch 必须是 dict")
                        else:
                            if not _coerce_float(stretch.get("delta_mm")):
                                errors.append(
                                    "add.post_transform_overrides.stretch.delta_mm 必须是数值"
                                )

        constraint = constraints_map.get(change.target_part)
        if constraint is not None:
            allowed_ops = set(constraint.get("allowed_ops", []) or [])
            forbidden_ops = set(constraint.get("forbidden_ops", []) or [])

            if constraint.get("is_virtual_part", False) and change.op != "add":
                errors.append("虚拟部件不允许直接编辑")

            if change.op == "stretch" and "stretch" not in allowed_ops:
                errors.append("该部件不允许 stretch")
            if change.op == "rotate" and "rotate" not in allowed_ops:
                errors.append("该部件不允许 rotate")
            if change.op == "translate" and "translate" not in allowed_ops:
                errors.append("该部件不允许 translate")
            if change.op == "scale" and "uniform_scale" in forbidden_ops and "delta_mm" not in p:
                errors.append("该部件禁止 uniform scale")
            if change.op == "delete" and "delete_core" in forbidden_ops:
                errors.append("该部件禁止 delete")

        results.append(
            ValidationResult(
                index=i,
                valid=len(errors) == 0,
                errors=errors,
                change=change,
            )
        )

    return results