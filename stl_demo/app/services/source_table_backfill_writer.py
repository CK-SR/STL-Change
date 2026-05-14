from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

import pandas as pd
import trimesh

from app.models import SkillExecutionResult

SOURCE_TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "2.1": {"filename": "2.1目标基本信息数据.csv", "keys": ["目标ID"]},
    "3.1": {"filename": "3.1目标物理结构数据.csv", "keys": ["目标ID", "部件ID"]},
    "3.2": {"filename": "3.2目标三维模型数据.csv", "keys": ["目标ID", "部件ID"]},
    "4.1": {"filename": "4.1目标功能结构数据.csv", "keys": ["目标ID", "功能ID"]},
    "4.3": {"filename": "4.3目标功能与部件映射数据.csv", "keys": ["目标ID", "功能ID", "部件ID"]},
}

_PART_ID_VERBOSE_COL = "部件ID（命名规则：BJ+四位数，范围BJ0001~ BJ9999。）"
_FUNCTION_ID_VERBOSE_COL = "功能ID（命名规则：GN+四位数，范围GN0001~ GN9999。）"

_LENGTH_ALIASES = ["长度(mm)", "长度", "长", "length"]
_WIDTH_ALIASES = ["宽度(mm)", "宽度", "宽", "width"]
_HEIGHT_ALIASES = ["高度(mm)", "高度", "高", "height"]
_POS_X_ALIASES = ["位置X", "位置x", "几何中心x(mm)", "中心X", "坐标X", "pos_x", "position_x"]
_POS_Y_ALIASES = ["位置Y", "位置y", "几何中心y(mm)", "中心Y", "坐标Y", "pos_y", "position_y"]
_POS_Z_ALIASES = ["位置Z", "位置z", "几何中心z(mm)", "中心Z", "坐标Z", "pos_z", "position_z"]
_FILE_ALIASES = ["三维模型数据文件", "模型文件", "STL文件", "部件文件", "文件路径"]
_NAME_ALIASES = ["部件名称", "名称", "part_name"]
_PARENT_ID_ALIASES = ["父部件ID", "父级部件ID", "parent_part_id"]
_PARENT_NAME_ALIASES = ["父部件名称", "父级部件名称", "parent_part_name"]
_CATEGORY_ALIASES = ["部件类别", "类别", "category"]
_STATUS_ALIASES = ["变更状态", "状态", "删除标记"]
_NOTE_ALIASES = ["备注", "说明", "变更说明", "note"]


@dataclass
class SourceTableSyncResult:
    output_dir: Path
    paths: Dict[str, str] = field(default_factory=dict)
    updates: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "paths": self.paths,
            "updates": self.updates,
            "warnings": self.warnings,
        }


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def read_csv_auto(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "gbk", "gb18030", "utf-8"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            df = pd.read_csv(path, encoding=encoding)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"读取失败: {path}: {last_error}")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def normalize_source_table_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename_map = {}
    if _PART_ID_VERBOSE_COL in out.columns and "部件ID" not in out.columns:
        rename_map[_PART_ID_VERBOSE_COL] = "部件ID"
    if _FUNCTION_ID_VERBOSE_COL in out.columns and "功能ID" not in out.columns:
        rename_map[_FUNCTION_ID_VERBOSE_COL] = "功能ID"
    return out.rename(columns=rename_map) if rename_map else out


def load_source_tables(csv_dir: Path) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    tables: Dict[str, pd.DataFrame] = {}
    warnings: List[str] = []
    for table_id, spec in SOURCE_TABLE_SPECS.items():
        path = csv_dir / spec["filename"]
        if not path.exists():
            warnings.append(f"source_table_missing[{table_id}]={path}")
            continue
        tables[table_id] = normalize_source_table_df(read_csv_auto(path))
    return tables, warnings


def find_first_col(columns: Iterable[str], aliases: Iterable[str]) -> str | None:
    normalized = [(str(col).strip(), str(col).strip().lower().replace(" ", "")) for col in columns]
    for alias in aliases:
        alias_norm = str(alias).strip().lower().replace(" ", "")
        if not alias_norm:
            continue
        for original, col_norm in normalized:
            if alias_norm == col_norm or alias_norm in col_norm:
                return original
    return None


def find_part_row_indices(df: pd.DataFrame, part_id: str) -> List[int]:
    if "部件ID" not in df.columns:
        return []
    target = safe_str(part_id)
    return [idx for idx, row in df.iterrows() if safe_str(row.get("部件ID")) == target]


def set_cell(df: pd.DataFrame, row_idx: int, column: str | None, value: Any) -> bool:
    if not column or column not in df.columns or safe_str(value) == "":
        return False
    if not pd.api.types.is_object_dtype(df[column].dtype):
        df[column] = df[column].astype("object")
    old_value = safe_str(df.at[row_idx, column])
    new_value = safe_str(value)
    if old_value == new_value:
        return False
    df.at[row_idx, column] = value
    return True


def append_note(df: pd.DataFrame, row_idx: int, note: str) -> bool:
    note_col = find_first_col(df.columns, _NOTE_ALIASES)
    if not note_col or not note:
        return False
    if not pd.api.types.is_object_dtype(df[note_col].dtype):
        df[note_col] = df[note_col].astype("object")
    old_note = safe_str(df.at[row_idx, note_col])
    if note in old_note:
        return False
    df.at[row_idx, note_col] = f"{old_note}; {note}" if old_note else note
    return True


def mesh_features(stl_path: Path) -> Dict[str, float]:
    mesh = trimesh.load_mesh(stl_path, process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    bounds = mesh.bounds
    extents = bounds[1] - bounds[0]
    center = (bounds[0] + bounds[1]) / 2.0
    return {
        "length": round(float(extents[0]), 6),
        "width": round(float(extents[1]), 6),
        "height": round(float(extents[2]), 6),
        "position_x": round(float(center[0]), 6),
        "position_y": round(float(center[1]), 6),
        "position_z": round(float(center[2]), 6),
    }


def update_geometry_columns(df: pd.DataFrame, row_idx: int, features: Mapping[str, Any]) -> int:
    col_map = {
        "length": find_first_col(df.columns, _LENGTH_ALIASES),
        "width": find_first_col(df.columns, _WIDTH_ALIASES),
        "height": find_first_col(df.columns, _HEIGHT_ALIASES),
        "position_x": find_first_col(df.columns, _POS_X_ALIASES),
        "position_y": find_first_col(df.columns, _POS_Y_ALIASES),
        "position_z": find_first_col(df.columns, _POS_Z_ALIASES),
    }
    updates = 0
    for key, column in col_map.items():
        updates += int(set_cell(df, row_idx, column, features.get(key)))
    return updates


def update_file_column(df: pd.DataFrame, row_idx: int, stl_path: Path) -> int:
    file_col = find_first_col(df.columns, _FILE_ALIASES)
    return int(set_cell(df, row_idx, file_col, stl_path.name))


def part_name_map(physical_df: pd.DataFrame | None) -> Dict[str, str]:
    if physical_df is None or "部件ID" not in physical_df.columns:
        return {}
    name_col = find_first_col(physical_df.columns, _NAME_ALIASES)
    if not name_col:
        return {}
    return {safe_str(row.get("部件ID")): safe_str(row.get(name_col)) for _, row in physical_df.iterrows()}


def target_id_for_part(physical_df: pd.DataFrame | None, part_id: str) -> str:
    if physical_df is None or "部件ID" not in physical_df.columns or "目标ID" not in physical_df.columns:
        return ""
    rows = physical_df[physical_df["部件ID"].map(safe_str) == safe_str(part_id)]
    if not rows.empty:
        return safe_str(rows.iloc[0].get("目标ID"))
    for _, row in physical_df.iterrows():
        target_id = safe_str(row.get("目标ID"))
        if target_id:
            return target_id
    return ""


def collect_changed_part_outputs(result: SkillExecutionResult) -> Dict[str, Path]:
    changed: Dict[str, Path] = {}
    metadata = result.metadata or {}
    affected_parts = metadata.get("affected_parts") or []
    output_files = [Path(str(path)) for path in result.output_files or []]
    if isinstance(affected_parts, list):
        for idx, item in enumerate(affected_parts):
            if not isinstance(item, dict):
                continue
            part_id = safe_str(item.get("part_id"))
            if not part_id:
                continue
            if idx < len(output_files):
                changed[part_id] = output_files[idx]
            else:
                temp_output = safe_str(item.get("temp_output_path"))
                if temp_output:
                    changed[part_id] = Path(temp_output)
    if result.target_part and result.output_files and result.target_part not in changed:
        changed[safe_str(result.target_part)] = output_files[0]
    return changed


def append_row_if_missing(df: pd.DataFrame, row_data: Mapping[str, Any], key_columns: Iterable[str]) -> Tuple[pd.DataFrame, bool]:
    keys = list(key_columns)
    for _, row in df.iterrows():
        if all(safe_str(row.get(key)) == safe_str(row_data.get(key)) for key in keys):
            return df, False
    new_row = {col: row_data.get(col, "") for col in df.columns}
    return pd.concat([df, pd.DataFrame([new_row], columns=df.columns)], ignore_index=True), True


def build_add_rows(
    result: SkillExecutionResult,
    physical_df: pd.DataFrame | None,
    model_df: pd.DataFrame | None,
    output_path: Path | None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    part_id = safe_str(result.target_part)
    metadata = result.metadata or {}
    attach_to = safe_str(metadata.get("attach_to"))
    asset_request = metadata.get("asset_request_used") if isinstance(metadata.get("asset_request_used"), dict) else {}
    asset_candidate = metadata.get("selected_asset_candidate") if isinstance(metadata.get("selected_asset_candidate"), dict) else {}
    asset_metadata = asset_candidate.get("asset_metadata") if isinstance(asset_candidate.get("asset_metadata"), dict) else {}
    parent_names = part_name_map(physical_df)
    target_id = target_id_for_part(physical_df, attach_to) or target_id_for_part(physical_df, part_id)
    content = safe_str(asset_request.get("content"))
    asset_name = safe_str(asset_metadata.get("name")) or safe_str(asset_request.get("name"))
    part_name = asset_name or (content[:30] if content else part_id)
    category = safe_str(asset_metadata.get("category")) or safe_str(asset_request.get("category")) or "新增部件"

    physical_row = {
        "目标ID": target_id,
        "部件ID": part_id,
        "部件名称": part_name,
        "父部件ID": attach_to,
        "父部件名称": parent_names.get(attach_to, ""),
        "部件类别": category,
        "备注": result.message,
    }
    model_row = {
        "目标ID": target_id,
        "部件ID": part_id,
        "三维模型数据文件": output_path.name if output_path else f"{part_id}.stl",
        "备注": result.message,
    }
    return physical_row, model_row


def sync_add_result(tables: Dict[str, pd.DataFrame], result: SkillExecutionResult, output_path: Path | None) -> Dict[str, int]:
    updates: Dict[str, int] = {}
    physical_df = tables.get("3.1")
    model_df = tables.get("3.2")
    physical_row, model_row = build_add_rows(result, physical_df, model_df, output_path)
    features: Dict[str, float] = {}
    if output_path and output_path.exists():
        try:
            features = mesh_features(output_path)
        except Exception:
            features = {}

    if physical_df is not None:
        physical_df, appended = append_row_if_missing(physical_df, physical_row, ["目标ID", "部件ID"])
        tables["3.1"] = physical_df
        if appended:
            updates["3.1"] = updates.get("3.1", 0) + 1
        for idx in find_part_row_indices(physical_df, safe_str(result.target_part)):
            updates["3.1"] = updates.get("3.1", 0) + update_geometry_columns(physical_df, idx, features)
            updates["3.1"] += int(append_note(physical_df, idx, f"STL同步:add:{result.message}"))

    if model_df is not None:
        model_df, appended = append_row_if_missing(model_df, model_row, ["目标ID", "部件ID"])
        tables["3.2"] = model_df
        if appended:
            updates["3.2"] = updates.get("3.2", 0) + 1
        for idx in find_part_row_indices(model_df, safe_str(result.target_part)):
            if output_path:
                updates["3.2"] = updates.get("3.2", 0) + update_file_column(model_df, idx, output_path)
            updates["3.2"] = updates.get("3.2", 0) + update_geometry_columns(model_df, idx, features)
            updates["3.2"] += int(append_note(model_df, idx, f"STL同步:add:{result.message}"))
    return {table_id: count for table_id, count in updates.items() if count}


def sync_existing_part_result(tables: Dict[str, pd.DataFrame], result: SkillExecutionResult) -> Dict[str, int]:
    updates: Dict[str, int] = {}
    changed_outputs = collect_changed_part_outputs(result)
    target_parts = list(changed_outputs.keys()) or ([safe_str(result.target_part)] if result.target_part else [])

    for part_id in target_parts:
        output_path = changed_outputs.get(part_id)
        features: Dict[str, float] = {}
        if output_path and output_path.exists():
            try:
                features = mesh_features(output_path)
            except Exception:
                features = {}
        for table_id in ["3.1", "3.2"]:
            df = tables.get(table_id)
            if df is None:
                continue
            row_indices = find_part_row_indices(df, part_id)
            for idx in row_indices:
                updates[table_id] = updates.get(table_id, 0) + update_geometry_columns(df, idx, features)
                if output_path and table_id == "3.2":
                    updates[table_id] += update_file_column(df, idx, output_path)
                updates[table_id] += int(append_note(df, idx, f"STL同步:{result.op}:{result.message}"))

    if result.op == "delete":
        part_id = safe_str(result.target_part)
        for table_id in ["3.1", "3.2"]:
            df = tables.get(table_id)
            if df is None:
                continue
            status_col = find_first_col(df.columns, _STATUS_ALIASES)
            for idx in find_part_row_indices(df, part_id):
                updates[table_id] = updates.get(table_id, 0) + int(set_cell(df, idx, status_col, "已删除"))
                updates[table_id] += int(append_note(df, idx, f"STL同步:delete:{result.message}"))
    return {table_id: count for table_id, count in updates.items() if count}


def merge_update_counts(target: Dict[str, int], source: Mapping[str, int]) -> None:
    for table_id, count in source.items():
        target[table_id] = target.get(table_id, 0) + int(count)


def sync_execution_results_to_tables(
    tables: Dict[str, pd.DataFrame],
    execution_results: Iterable[SkillExecutionResult],
) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    updates: Dict[str, int] = {}
    applied: List[Dict[str, Any]] = []
    for result in execution_results:
        if not result.success:
            continue
        if result.op == "add":
            output_path = Path(result.output_files[0]) if result.output_files else None
            result_updates = sync_add_result(tables, result, output_path)
        else:
            result_updates = sync_existing_part_result(tables, result)
        if result_updates:
            merge_update_counts(updates, result_updates)
            applied.append(
                {
                    "target_part": result.target_part,
                    "op": result.op,
                    "updates": result_updates,
                    "output_files": result.output_files,
                    "message": result.message,
                }
            )
    return updates, applied


def export_source_table_syncs(
    *,
    csv_dir: Path,
    output_dir: Path,
    execution_results: Iterable[SkillExecutionResult],
) -> SourceTableSyncResult:
    """Write copied source CSV tables synchronized with successful STL execution results only."""
    tables, warnings = load_source_tables(csv_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = SourceTableSyncResult(output_dir=output_dir, warnings=warnings)
    if not tables:
        result.warnings.append(f"source_table_sync_skipped=no_tables:{csv_dir}")
        return result

    updates, applied = sync_execution_results_to_tables(tables, execution_results)
    for table_id, df in tables.items():
        output_path = output_dir / SOURCE_TABLE_SPECS[table_id]["filename"]
        write_csv(df, output_path)
        result.paths[table_id] = str(output_path)

    result.updates = updates
    detail_path = output_dir / "source_table_sync_report.json"
    detail = {
        "updates_by_table": updates,
        "applied_execution_results": applied,
        "warnings": result.warnings,
    }
    detail_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    result.paths["report"] = str(detail_path)
    return result
