from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import pandas as pd

from app.models import ChangeIntent


def _ensure_audit_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "被修改参数" not in out.columns:
        out["被修改参数"] = ""
    if "参数原始值->新值" not in out.columns:
        out["参数原始值->新值"] = ""
    if "变更状态" not in out.columns:
        out["变更状态"] = ""
    if "备注" not in out.columns:
        out["备注"] = ""
    return out


def _get_part_name_from_row(row: pd.Series, schema: Dict[str, Any]) -> str | None:
    file_col = schema.get("file_col")
    name_col = schema.get("name_col")

    if file_col and pd.notna(row.get(file_col)):
        return Path(str(row[file_col]).strip()).name

    if name_col and pd.notna(row.get(name_col)):
        name = str(row[name_col]).strip()
        return name if name.endswith(".stl") else f"{name}.stl"

    return None


def _find_row_indices_by_part(df: pd.DataFrame, schema: Dict[str, Any], part_name: str) -> List[int]:
    indices: List[int] = []
    target = Path(part_name).name

    for idx, row in df.iterrows():
        row_part = _get_part_name_from_row(row, schema)
        if row_part and Path(row_part).name == target:
            indices.append(idx)

    return indices


def _append_audit(df: pd.DataFrame, idx: int, field_name: str, from_to: str) -> None:
    if str(df.at[idx, "被修改参数"]).strip():
        df.at[idx, "被修改参数"] = f'{df.at[idx, "被修改参数"]};{field_name}'
        df.at[idx, "参数原始值->新值"] = f'{df.at[idx, "参数原始值->新值"]};{from_to}'
    else:
        df.at[idx, "被修改参数"] = field_name
        df.at[idx, "参数原始值->新值"] = from_to


def build_change_table_from_intent(change_intent: ChangeIntent, df: pd.DataFrame, schema: Dict[str, Any]) -> pd.DataFrame:
    model_col = schema.get("model_col")
    category_col = schema.get("category_col")

    model_name = ""
    if model_col and len(df) > 0 and model_col in df.columns:
        model_name = str(df.iloc[0][model_col])

    rows = []
    for i, ch in enumerate(change_intent.changes, start=1):
        category = ""
        indices = _find_row_indices_by_part(df, schema, ch.target_part)
        if indices and category_col and category_col in df.columns:
            category = str(df.loc[indices[0], category_col])

        direction = ""
        amplitude = ""
        if ch.op == "scale":
            direction = "x/y/z"
            amplitude = str(ch.params)
        elif ch.op == "translate":
            direction = "x/y/z"
            amplitude = str(ch.params)
        elif ch.op == "rotate":
            direction = str(ch.params.get("axis", ""))
            amplitude = str(ch.params.get("degrees", ""))
        elif ch.op == "add":
            direction = "offset"
            amplitude = str(ch.params.get("offset", {}))

        rows.append(
            {
                "变更ID": f"CHG-{i:03d}",
                "模型名称": model_name,
                "目标部件": ch.target_part,
                "目标类别": category,
                "变更类型": ch.op,
                "变更方向": direction,
                "变更幅度": amplitude,
                "联动部件": ch.params.get("source_part", "") if ch.op == "add" else "",
                "保持不变部件": "",
                "变更原因": ch.reason,
                "约束说明": "",
                "备注": "自动生成",
            }
        )

    columns = [
        "变更ID",
        "模型名称",
        "目标部件",
        "目标类别",
        "变更类型",
        "变更方向",
        "变更幅度",
        "联动部件",
        "保持不变部件",
        "变更原因",
        "约束说明",
        "备注",
    ]
    return pd.DataFrame(rows, columns=columns)


def apply_change_intent_to_excel(change_intent: ChangeIntent, df: pd.DataFrame, schema: Dict[str, Any]) -> pd.DataFrame:
    out = _ensure_audit_cols(df)

    file_col = schema.get("file_col")
    name_col = schema.get("name_col")
    dim_axis_map = schema.get("dim_axis_map", {})
    pos_axis_map = schema.get("pos_axis_map", {})

    for ch in change_intent.changes:
        indices = _find_row_indices_by_part(out, schema, ch.target_part)

        if ch.op == "scale":
            axis_to_scale = {
                "x": float(ch.params.get("x", 1.0)),
                "y": float(ch.params.get("y", 1.0)),
                "z": float(ch.params.get("z", 1.0)),
            }

            for axis in ["x", "y", "z"]:
                cols = dim_axis_map.get(axis, [])
                for col in cols:
                    for idx in indices:
                        old_val = pd.to_numeric(out.at[idx, col], errors="coerce")
                        if pd.notna(old_val):
                            new_val = old_val * axis_to_scale[axis]
                            out.at[idx, col] = new_val
                            _append_audit(out, idx, col, f"{old_val}->{new_val}")

            for idx in indices:
                out.at[idx, "变更状态"] = "已修改"
                note = f"scale {ch.params}"
                out.at[idx, "备注"] = f'{out.at[idx, "备注"]};{note}' if str(out.at[idx, "备注"]).strip() else note

        elif ch.op == "translate":
            axis_to_delta = {
                "x": float(ch.params.get("x", 0.0)),
                "y": float(ch.params.get("y", 0.0)),
                "z": float(ch.params.get("z", 0.0)),
            }

            for axis in ["x", "y", "z"]:
                cols = pos_axis_map.get(axis, [])
                for col in cols:
                    for idx in indices:
                        old_val = pd.to_numeric(out.at[idx, col], errors="coerce")
                        if pd.notna(old_val):
                            new_val = old_val + axis_to_delta[axis]
                            out.at[idx, col] = new_val
                            _append_audit(out, idx, col, f"{old_val}->{new_val}")

            for idx in indices:
                out.at[idx, "变更状态"] = "已修改"
                note = f"translate {ch.params}"
                out.at[idx, "备注"] = f'{out.at[idx, "备注"]};{note}' if str(out.at[idx, "备注"]).strip() else note

        elif ch.op == "rotate":
            for idx in indices:
                out.at[idx, "变更状态"] = "已修改"
                note = f"rotate {ch.params}"
                out.at[idx, "备注"] = f'{out.at[idx, "备注"]};{note}' if str(out.at[idx, "备注"]).strip() else note

        elif ch.op == "delete":
            for idx in indices:
                out.at[idx, "变更状态"] = "删除"
                note = "该部件对应 STL 已删除"
                out.at[idx, "备注"] = f'{out.at[idx, "备注"]};{note}' if str(out.at[idx, "备注"]).strip() else note

        elif ch.op == "add":
            source_part = str(ch.params.get("source_part", "")).strip()
            source_indices = _find_row_indices_by_part(out, schema, source_part)
            if not source_indices:
                continue

            src_idx = source_indices[0]
            new_row = out.loc[src_idx].copy()

            new_file_name = f"{Path(source_part).stem}_added_001.stl"

            if file_col and file_col in out.columns:
                new_row[file_col] = new_file_name
            if name_col and name_col in out.columns:
                new_row[name_col] = new_file_name

            new_row["被修改参数"] = "新增"
            new_row["参数原始值->新值"] = f"source={source_part};offset={ch.params.get('offset', {})}"
            new_row["变更状态"] = "新增"
            new_row["备注"] = f"add from {source_part}"

            out = pd.concat([out, pd.DataFrame([new_row])], ignore_index=True)

    return out