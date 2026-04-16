from __future__ import annotations

from typing import Any, Dict, List


def build_part_summary_from_constraints(part_constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []

    for item in part_constraints:
        geometry = item.get("geometry", {}) or {}
        summary.append(
            {
                "part_id": str(item.get("part_id", "")).strip(),
                "part_name": str(item.get("part_name", "")).strip(),
                "target_id": str(item.get("target_id", "")).strip(),
                "parent_part_id": str(item.get("parent_part_id", "")).strip(),
                "parent_part_name": str(item.get("parent_part_name", "")).strip(),
                "edit_type": str(item.get("edit_type", "")).strip(),
                "primary_axis": item.get("primary_axis", []),
                "anchor_mode": str(item.get("anchor_mode", "")).strip(),
                "symmetry_group": str(item.get("symmetry_group", "")).strip(),
                "neighbors": item.get("neighbors", []) or [],
                "allowed_ops": item.get("allowed_ops", []) or [],
                "forbidden_ops": item.get("forbidden_ops", []) or [],
                "clearance_min_mm": item.get("clearance_min_mm", 0.0),
                "has_stl_file": bool(item.get("has_stl_file", False)),
                "is_virtual_part": bool(item.get("is_virtual_part", False)),
                "geometry_valid": bool(item.get("geometry_valid", False)),
                "function_names": item.get("function_names", []) or [],
                "bbox_center": geometry.get("bbox_center", []) or [],
                "center_mass": geometry.get("center_mass", []) or [],
                "aabb_extents": geometry.get("aabb_extents", []) or [],
                "description": str(item.get("semantic_note", "")).strip(),
            }
        )

    return summary