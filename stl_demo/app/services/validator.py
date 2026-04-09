from __future__ import annotations

from typing import Dict, List
from app.models import ChangeIntent, ValidationResult

ALLOWED_OPS = {"scale", "translate", "rotate", "delete", "add"}


def _coerce_float(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_change_intent(
    intent: ChangeIntent,
    existing_parts: set[str],
) -> List[ValidationResult]:
    results: List[ValidationResult] = []

    for i, change in enumerate(intent.changes):
        errors: List[str] = []
        if change.target_part not in existing_parts:
            errors.append("target_part 不存在")
        if change.op not in ALLOWED_OPS:
            errors.append("op 不在允许列表")
        if not isinstance(change.params, Dict):
            errors.append("params 必须为 dict")

        p = change.params
        if change.op in {"scale", "translate"}:
            for axis in ["x", "y", "z"]:
                if axis not in p:
                    errors.append(f"缺少参数 {axis}")
                elif not _coerce_float(p.get(axis)):
                    errors.append(f"参数 {axis} 不是数值")
        elif change.op == "rotate":
            if p.get("axis") not in {"x", "y", "z"}:
                errors.append("rotate.axis 必须是 x/y/z")
            if not _coerce_float(p.get("degrees")):
                errors.append("rotate.degrees 必须是数值")
        elif change.op == "add":
            source_part = p.get("source_part")
            if source_part not in existing_parts:
                errors.append("add.source_part 不存在")
            offset = p.get("offset")
            if not isinstance(offset, dict):
                errors.append("add.offset 必须是 dict")
            else:
                for axis in ["x", "y", "z"]:
                    if axis not in offset or not _coerce_float(offset.get(axis)):
                        errors.append(f"add.offset.{axis} 非法")

        results.append(
            ValidationResult(
                index=i,
                valid=len(errors) == 0,
                errors=errors,
                change=change,
            )
        )
    return results
