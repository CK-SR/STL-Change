from __future__ import annotations

from typing import Any, Dict
import pandas as pd


def _find_first_col(columns: list[str], keywords: list[str]) -> str | None:
    for c in columns:
        lower_c = c.lower()
        for kw in keywords:
            if kw in lower_c:
                return c
    return None


def analyze_excel_schema(df: pd.DataFrame) -> Dict[str, Any]:
    cols = [str(c).strip() for c in df.columns]

    model_col = _find_first_col(cols, ["模型", "model"])
    object_type_col = _find_first_col(cols, ["对象类型", "object_type", "type"])
    category_col = _find_first_col(cols, ["部件类别", "类别", "category"])
    name_col = _find_first_col(cols, ["部件名称", "名称", "name"])
    file_col = _find_first_col(cols, ["部件文件", "文件", "路径", "stl", "file"])
    node_col = _find_first_col(cols, ["节点名称", "节点", "node"])

    dim_axis_map = {"x": [], "y": [], "z": []}
    pos_axis_map = {"x": [], "y": [], "z": []}

    for c in cols:
        lc = c.lower()

        # 尺寸
        if "长度" in c or lc in {"length"}:
            dim_axis_map["x"].append(c)
        elif "宽度" in c or lc in {"width"}:
            dim_axis_map["y"].append(c)
        elif "高度" in c or lc in {"height"}:
            dim_axis_map["z"].append(c)

        # 位置
        elif "位置x" in lc or c == "位置X":
            pos_axis_map["x"].append(c)
        elif "位置y" in lc or c == "位置Y":
            pos_axis_map["y"].append(c)
        elif "位置z" in lc or c == "位置Z":
            pos_axis_map["z"].append(c)

    dim_cols = dim_axis_map["x"] + dim_axis_map["y"] + dim_axis_map["z"]
    pos_cols = pos_axis_map["x"] + pos_axis_map["y"] + pos_axis_map["z"]

    return {
        "model_col": model_col,
        "object_type_col": object_type_col,
        "category_col": category_col,
        "name_col": name_col,
        "file_col": file_col,
        "node_col": node_col,
        "dim_cols": dim_cols,
        "dim_axis_map": dim_axis_map,
        "pos_cols": pos_cols,
        "pos_axis_map": pos_axis_map,
    }