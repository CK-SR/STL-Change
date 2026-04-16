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

        if change.target_part not in existing_parts and change.op != "add":
            errors.append("target_part 不存在")

        if change.op not in ALLOWED_OPS:
            errors.append("op 不在允许列表")

        if not isinstance(change.params, Dict):
            errors.append("params 必须为 dict")

        p = change.params if isinstance(change.params, Dict) else {}

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
            has_uniform_scale = all(k in p for k in ["x", "y", "z"])
            has_stretch = _coerce_float(p.get("delta_mm"))
            if not has_uniform_scale and not has_stretch:
                errors.append("scale 需提供 x/y/z，或提供 delta_mm")
            if has_uniform_scale:
                _validate_xyz_dict(errors, p)
            if "delta_mm" in p and not _coerce_float(p.get("delta_mm")):
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
            source_part = p.get("source_part")
            if source_part and source_part not in existing_parts:
                errors.append("add.source_part 不存在")
            offset = p.get("offset", {"x": 0, "y": 0, "z": 0})
            if not isinstance(offset, dict):
                errors.append("add.offset 必须是 dict")
            else:
                _validate_xyz_dict(errors, offset, prefix="offset.")

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