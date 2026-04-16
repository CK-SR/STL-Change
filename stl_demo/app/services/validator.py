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


def validate_change_intent(
    intent: ChangeIntent,
    existing_parts: set[str],
) -> List[ValidationResult]:
    results: List[ValidationResult] = []

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
            # 兼容旧版 uniform scale，也兼容新版 stretch 入口
            has_uniform_scale = all(k in p for k in ["x", "y", "z"])
            has_stretch = _coerce_float(p.get("delta_mm"))

            if not has_uniform_scale and not has_stretch:
                errors.append("scale 需提供 x/y/z，或提供 delta_mm 走受约束 stretch")

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
            if source_part not in existing_parts:
                errors.append("add.source_part 不存在")

            offset = p.get("offset")
            if not isinstance(offset, dict):
                errors.append("add.offset 必须是 dict")
            else:
                _validate_xyz_dict(errors, offset, prefix="offset.")

        results.append(
            ValidationResult(
                index=i,
                valid=len(errors) == 0,
                errors=errors,
                change=change,
            )
        )

    return results