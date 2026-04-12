from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import pandas as pd


def build_part_summary_from_excel(df: pd.DataFrame, schema: Dict[str, Any]) -> List[dict]:
    rows: List[dict] = []

    category_col = schema.get("category_col")
    name_col = schema.get("name_col")
    file_col = schema.get("file_col")
    node_col = schema.get("node_col")
    dim_cols = schema.get("dim_cols", [])
    pos_cols = schema.get("pos_cols", [])

    extra_candidate_cols = ["材质推断", "结构分区", "部件作用", "备注"]

    for _, row in df.iterrows():
        raw_name = ""
        if file_col and pd.notna(row.get(file_col)):
            raw_name = str(row[file_col]).strip()
            part_name = Path(raw_name).name
        elif name_col and pd.notna(row.get(name_col)):
            raw_name = str(row[name_col]).strip()
            part_name = raw_name if raw_name.endswith(".stl") else f"{raw_name}.stl"
        else:
            continue

        category = str(row.get(category_col, "")).strip() if category_col else ""
        display_name = str(row.get(name_col, "")).strip() if name_col else ""
        node_name = str(row.get(node_col, "")).strip() if node_col else ""

        dims = {c: row.get(c) for c in dim_cols if c in row.index}
        pos = {c: row.get(c) for c in pos_cols if c in row.index}

        extras = {}
        for c in extra_candidate_cols:
            if c in df.columns and pd.notna(row.get(c)):
                extras[c] = row.get(c)

        desc_parts = []
        if display_name:
            desc_parts.append(f"名称={display_name}")
        if category:
            desc_parts.append(f"类别={category}")
        if node_name:
            desc_parts.append(f"节点={node_name}")
        if dims:
            desc_parts.append(f"尺寸={dims}")
        if pos:
            desc_parts.append(f"位置={pos}")
        if extras:
            desc_parts.append(f"补充={extras}")

        rows.append(
            {
                "part_name": part_name,
                "file_path": raw_name if raw_name else part_name,
                "category": category,
                "confidence": 1.0,
                "description": "；".join(desc_parts),
            }
        )

    return rows