from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class PartGeometry:
    bbox_center: List[Optional[float]] = field(default_factory=list)
    center_mass: List[Optional[float]] = field(default_factory=list)
    aabb_extents: List[Optional[float]] = field(default_factory=list)


@dataclass
class PartConstraint:
    target_id: str
    part_id: str
    part_name: str
    parent_part_id: str = ""
    parent_part_name: str = ""
    edit_type: str = "general_part"
    primary_axis: List[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    anchor_mode: str = "center"
    symmetry_group: str = ""
    neighbors: List[str] = field(default_factory=list)
    allowed_ops: List[str] = field(default_factory=list)
    forbidden_ops: List[str] = field(default_factory=list)
    clearance_min_mm: float = 2.0
    has_stl_file: bool = False
    is_virtual_part: bool = False
    geometry_valid: bool = False
    geometry: PartGeometry = field(default_factory=PartGeometry)
    function_names: List[str] = field(default_factory=list)
    semantic_note: str = ""

    # 新增：挂载/联动关系
    attachment_parent_part_id: str = ""
    attachment_parent_part_name: str = ""
    link_type: str = ""
    follow_transform_of: str = ""
    follow_ops: List[str] = field(default_factory=list)
    linked_children: List[str] = field(default_factory=list)
    linked_children_names: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PartConstraint":
        geometry_data = data.get("geometry", {}) or {}
        geometry = PartGeometry(
            bbox_center=list(geometry_data.get("bbox_center", []) or []),
            center_mass=list(geometry_data.get("center_mass", []) or []),
            aabb_extents=list(geometry_data.get("aabb_extents", []) or []),
        )

        primary_axis = list(data.get("primary_axis", []) or [0.0, 0.0, 1.0])
        if len(primary_axis) != 3:
            primary_axis = [0.0, 0.0, 1.0]

        return cls(
            target_id=str(data.get("target_id", "")).strip(),
            part_id=str(data.get("part_id", "")).strip(),
            part_name=str(data.get("part_name", "")).strip(),
            parent_part_id=str(data.get("parent_part_id", "")).strip(),
            parent_part_name=str(data.get("parent_part_name", "")).strip(),
            edit_type=str(data.get("edit_type", "general_part")).strip(),
            primary_axis=[float(x) for x in primary_axis],
            anchor_mode=str(data.get("anchor_mode", "center")).strip(),
            symmetry_group=str(data.get("symmetry_group", "")).strip(),
            neighbors=[str(x).strip() for x in data.get("neighbors", []) or [] if str(x).strip()],
            allowed_ops=[str(x).strip() for x in data.get("allowed_ops", []) or [] if str(x).strip()],
            forbidden_ops=[str(x).strip() for x in data.get("forbidden_ops", []) or [] if str(x).strip()],
            clearance_min_mm=float(data.get("clearance_min_mm", 2.0) or 2.0),
            has_stl_file=bool(data.get("has_stl_file", False)),
            is_virtual_part=bool(data.get("is_virtual_part", False)),
            geometry_valid=bool(data.get("geometry_valid", False)),
            geometry=geometry,
            function_names=[str(x).strip() for x in data.get("function_names", []) or [] if str(x).strip()],
            semantic_note=str(data.get("semantic_note", "")).strip(),
            attachment_parent_part_id=str(data.get("attachment_parent_part_id", "")).strip(),
            attachment_parent_part_name=str(data.get("attachment_parent_part_name", "")).strip(),
            link_type=str(data.get("link_type", "")).strip(),
            follow_transform_of=str(data.get("follow_transform_of", "")).strip(),
            follow_ops=[str(x).strip() for x in data.get("follow_ops", []) or [] if str(x).strip()],
            linked_children=[str(x).strip() for x in data.get("linked_children", []) or [] if str(x).strip()],
            linked_children_names=[str(x).strip() for x in data.get("linked_children_names", []) or [] if str(x).strip()],
        )


class PartConstraintService:
    def __init__(self, constraint_json_path: str | Path) -> None:
        self.constraint_json_path = Path(constraint_json_path)
        self._constraints_by_part_id: Dict[str, PartConstraint] = {}
        self._constraints_by_target_id: Dict[str, List[PartConstraint]] = {}
        self._symmetry_groups: Dict[str, List[str]] = {}
        self.reload()

    def reload(self) -> None:
        if not self.constraint_json_path.exists():
            raise FileNotFoundError(f"Constraint file not found: {self.constraint_json_path}")

        raw = json.loads(self.constraint_json_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("part_constraints.json must be a list")

        self._constraints_by_part_id.clear()
        self._constraints_by_target_id.clear()
        self._symmetry_groups.clear()

        for item in raw:
            constraint = PartConstraint.from_dict(item)
            if not constraint.part_id:
                continue

            self._constraints_by_part_id[constraint.part_id] = constraint
            self._constraints_by_target_id.setdefault(constraint.target_id, []).append(constraint)

            if constraint.symmetry_group:
                self._symmetry_groups.setdefault(constraint.symmetry_group, []).append(constraint.part_id)

    def get_part_constraint(self, part_id: str) -> Optional[PartConstraint]:
        return self._constraints_by_part_id.get(part_id)

    def require_part_constraint(self, part_id: str) -> PartConstraint:
        constraint = self.get_part_constraint(part_id)
        if constraint is None:
            raise KeyError(f"Constraint not found for part_id={part_id}")
        return constraint

    def list_target_constraints(self, target_id: str) -> List[PartConstraint]:
        return list(self._constraints_by_target_id.get(target_id, []))

    def list_neighbors(self, part_id: str) -> List[str]:
        return list(self.require_part_constraint(part_id).neighbors)

    def list_symmetry_mates(self, part_id: str) -> List[str]:
        constraint = self.require_part_constraint(part_id)
        if not constraint.symmetry_group:
            return []
        mates = self._symmetry_groups.get(constraint.symmetry_group, [])
        return [x for x in mates if x != part_id]

    def get_primary_axis(self, part_id: str) -> List[float]:
        return list(self.require_part_constraint(part_id).primary_axis)

    def get_anchor_mode(self, part_id: str) -> str:
        return self.require_part_constraint(part_id).anchor_mode

    def get_clearance_min_mm(self, part_id: str) -> float:
        return float(self.require_part_constraint(part_id).clearance_min_mm)

    def get_allowed_ops(self, part_id: str) -> Set[str]:
        return set(self.require_part_constraint(part_id).allowed_ops)

    def get_forbidden_ops(self, part_id: str) -> Set[str]:
        return set(self.require_part_constraint(part_id).forbidden_ops)

    def is_operation_allowed(self, part_id: str, op_name: str) -> bool:
        constraint = self.require_part_constraint(part_id)
        op_name = op_name.strip()

        if not op_name:
            return False
        if op_name in constraint.forbidden_ops:
            return False
        if constraint.allowed_ops and op_name not in constraint.allowed_ops:
            return False
        return True

    def assert_operation_allowed(self, part_id: str, op_name: str) -> None:
        if not self.is_operation_allowed(part_id, op_name):
            c = self.require_part_constraint(part_id)
            raise PermissionError(
                f"Operation '{op_name}' is not allowed for part_id={part_id}. "
                f"allowed={c.allowed_ops}, forbidden={c.forbidden_ops}"
            )

    def is_virtual_part(self, part_id: str) -> bool:
        return bool(self.require_part_constraint(part_id).is_virtual_part)

    def get_geometry_hint(self, part_id: str) -> PartGeometry:
        return self.require_part_constraint(part_id).geometry

    # ===== 联动关系 =====

    def get_follow_transform_of(self, part_id: str) -> str:
        return self.require_part_constraint(part_id).follow_transform_of

    def get_follow_ops(self, part_id: str) -> List[str]:
        return list(self.require_part_constraint(part_id).follow_ops)

    def get_attachment_parent_part_id(self, part_id: str) -> str:
        return self.require_part_constraint(part_id).attachment_parent_part_id

    def get_link_type(self, part_id: str) -> str:
        return self.require_part_constraint(part_id).link_type

    def list_linked_children(self, part_id: str, op_name: Optional[str] = None) -> List[str]:
        c = self.require_part_constraint(part_id)
        children = list(c.linked_children)

        if not op_name:
            return children

        result: List[str] = []
        for child_id in children:
            child = self.get_part_constraint(child_id)
            if child is None:
                continue
            if child.follow_transform_of != part_id:
                continue
            if child.follow_ops and op_name not in child.follow_ops:
                continue
            result.append(child_id)
        return result

    def summarize(self, part_id: str) -> Dict[str, Any]:
        c = self.require_part_constraint(part_id)
        return {
            "part_id": c.part_id,
            "part_name": c.part_name,
            "edit_type": c.edit_type,
            "primary_axis": c.primary_axis,
            "anchor_mode": c.anchor_mode,
            "neighbors": c.neighbors,
            "allowed_ops": c.allowed_ops,
            "forbidden_ops": c.forbidden_ops,
            "clearance_min_mm": c.clearance_min_mm,
            "is_virtual_part": c.is_virtual_part,
            "geometry_valid": c.geometry_valid,
            "symmetry_group": c.symmetry_group,
            "attachment_parent_part_id": c.attachment_parent_part_id,
            "attachment_parent_part_name": c.attachment_parent_part_name,
            "link_type": c.link_type,
            "follow_transform_of": c.follow_transform_of,
            "follow_ops": c.follow_ops,
            "linked_children": c.linked_children,
            "linked_children_names": c.linked_children_names,
        }