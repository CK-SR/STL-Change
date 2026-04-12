from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import pandas as pd


def _part_name_from_row(row: pd.Series, schema: Dict[str, Any]) -> str | None:
    file_col = schema.get("file_col")
    name_col = schema.get("name_col")

    if file_col and pd.notna(row.get(file_col)):
        return Path(str(row[file_col]).strip()).name

    if name_col and pd.notna(row.get(name_col)):
        name = str(row[name_col]).strip()
        return name if name.endswith(".stl") else f"{name}.stl"

    return None


def build_existing_parts_set_from_excel(df: pd.DataFrame, schema: Dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for _, row in df.iterrows():
        part_name = _part_name_from_row(row, schema)
        if part_name:
            result.add(part_name)
    return result


def build_part_to_file_map_from_excel(df: pd.DataFrame, schema: Dict[str, Any], output_dir: Path) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for _, row in df.iterrows():
        part_name = _part_name_from_row(row, schema)
        if part_name:
            result[part_name] = output_dir / part_name
    return result