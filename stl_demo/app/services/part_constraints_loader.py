from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set


def load_part_constraints(constraints_path: str | Path) -> List[dict]:
    path = Path(constraints_path)
    if not path.exists():
        raise FileNotFoundError(f"part_constraints.json not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("part_constraints.json must be a list of objects")
    return data


def build_existing_parts_set_from_constraints(part_constraints: List[dict]) -> Set[str]:
    result: Set[str] = set()
    for item in part_constraints:
        part_id = str(item.get("part_id", "")).strip()
        part_name = str(item.get("part_name", "")).strip()
        if part_id:
            result.add(part_id)
        if part_name:
            result.add(part_name)
    return result


def build_part_to_file_map_from_constraints(
    part_constraints: List[dict],
    stl_dir: str | Path,
) -> Dict[str, Path]:
    stl_dir = Path(stl_dir)
    filename_map = {p.name: p for p in stl_dir.glob("*.stl")}

    result: Dict[str, Path] = {}
    for item in part_constraints:
        part_id = str(item.get("part_id", "")).strip()
        part_name = str(item.get("part_name", "")).strip()

        candidate = None
        candidates: List[str] = []
        if part_name:
            candidates.extend([part_name, f"{part_name}.stl"])
        if part_id:
            candidates.extend([part_id, f"{part_id}.stl"])

        for key in candidates:
            if key in filename_map:
                candidate = filename_map[key]
                break

        if candidate is not None:
            if part_id:
                result[part_id] = candidate
            if part_name:
                result[part_name] = candidate

    return result