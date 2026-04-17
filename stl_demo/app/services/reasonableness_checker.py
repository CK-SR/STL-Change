from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import trimesh


@dataclass
class CheckItem:
    name: str
    passed: bool
    detail: str
    severity: str = "info"


@dataclass
class ReasonablenessReport:
    part_id: str
    op: str
    input_path: str
    output_path: str
    status: str
    checks: List[Dict[str, Any]]
    warnings: List[str]
    summary: str = ""


def _load_mesh(path: str | Path) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(path, process=False)
    if isinstance(mesh, trimesh.Scene):
        if len(mesh.geometry) == 0:
            raise ValueError(f"No geometry in scene: {path}")
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Loaded object is not Trimesh: {type(mesh)}")
    if len(mesh.vertices) == 0:
        raise ValueError(f"Mesh has no vertices: {path}")
    return mesh.copy()


def _bounds_overlap_1d(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    return min(a_max, b_max) - max(a_min, b_min)


def _aabb_collision_and_gap(
    mesh_a: trimesh.Trimesh,
    mesh_b: trimesh.Trimesh,
) -> Tuple[bool, float]:
    """
    返回:
    - collision: AABB 是否相交
    - gap: AABB 最小间隙（相交时为 0）
    """
    a_min, a_max = mesh_a.bounds
    b_min, b_max = mesh_b.bounds

    overlaps = []
    gaps = []

    for i in range(3):
        overlap = _bounds_overlap_1d(a_min[i], a_max[i], b_min[i], b_max[i])
        overlaps.append(overlap)
        if overlap >= 0:
            gaps.append(0.0)
        else:
            gaps.append(-overlap)

    collision = all(x >= 0 for x in overlaps)
    gap = float(max(gaps)) if collision else float(np.linalg.norm(gaps))
    return collision, gap


def _extent_along_axis(mesh: trimesh.Trimesh, axis: List[float]) -> float:
    axis_vec = np.asarray(axis, dtype=float).reshape(3)
    norm = np.linalg.norm(axis_vec)
    if norm < 1e-9:
        return 0.0
    axis_vec = axis_vec / norm
    projections = np.dot(mesh.vertices, axis_vec)
    return float(projections.max() - projections.min())


def _safe_ratio(new_value: float, old_value: float) -> Optional[float]:
    if abs(old_value) < 1e-9:
        return None
    return float(new_value / old_value)


def _find_constraint(part_constraints: List[dict], part_id: str) -> Optional[dict]:
    for item in part_constraints:
        if str(item.get("part_id", "")).strip() == part_id:
            return item
    return None


def _get_neighbor_ids(constraint: Optional[dict]) -> List[str]:
    if not constraint:
        return []
    return [str(x).strip() for x in constraint.get("neighbors", []) or [] if str(x).strip()]


def _get_symmetry_group(constraint: Optional[dict]) -> str:
    if not constraint:
        return ""
    return str(constraint.get("symmetry_group", "")).strip()


def _get_symmetry_mates(part_constraints: List[dict], part_id: str, symmetry_group: str) -> List[str]:
    if not symmetry_group:
        return []
    mates: List[str] = []
    for item in part_constraints:
        item_pid = str(item.get("part_id", "")).strip()
        item_group = str(item.get("symmetry_group", "")).strip()
        if item_pid and item_pid != part_id and item_group == symmetry_group:
            mates.append(item_pid)
    return mates


def _get_primary_axis(constraint: Optional[dict]) -> List[float]:
    if not constraint:
        return [1.0, 0.0, 0.0]
    axis = list(constraint.get("primary_axis", []) or [1.0, 0.0, 0.0])
    if len(axis) != 3:
        return [1.0, 0.0, 0.0]
    try:
        return [float(x) for x in axis]
    except Exception:
        return [1.0, 0.0, 0.0]


def _get_clearance_min_mm(constraint: Optional[dict]) -> float:
    if not constraint:
        return 2.0
    try:
        return float(constraint.get("clearance_min_mm", 2.0) or 2.0)
    except Exception:
        return 2.0


def _make_item(name: str, passed: bool, detail: str, severity: str = "info") -> CheckItem:
    return CheckItem(name=name, passed=passed, detail=detail, severity=severity)


def check_reasonableness(
    *,
    part_id: str,
    op: str,
    input_path: str | Path,
    output_path: str | Path,
    part_to_file: Dict[str, Path],
    part_constraints: List[dict],
) -> ReasonablenessReport:
    input_path = str(input_path)
    output_path = str(output_path)

    warnings: List[str] = []
    checks: List[CheckItem] = []

    try:
        old_mesh = _load_mesh(input_path)
        new_mesh = _load_mesh(output_path)
    except Exception as exc:
        return ReasonablenessReport(
            part_id=part_id,
            op=op,
            input_path=input_path,
            output_path=output_path,
            status="warning",
            checks=[asdict(_make_item("load_mesh", False, f"failed to load mesh: {exc}", "error"))],
            warnings=[],
            summary="reasonableness check skipped because mesh loading failed",
        )

    constraint = _find_constraint(part_constraints, part_id)
    if constraint is None:
        warnings.append(f"constraint not found for part_id={part_id}, using fallback checks only")

    primary_axis = _get_primary_axis(constraint)
    clearance_min_mm = _get_clearance_min_mm(constraint)
    neighbor_ids = _get_neighbor_ids(constraint)
    symmetry_group = _get_symmetry_group(constraint)

    # 1) watertight / winding 基础状态
    checks.append(
        _make_item(
            "mesh_basic",
            bool(new_mesh.is_winding_consistent),
            f"is_watertight={new_mesh.is_watertight}, is_winding_consistent={new_mesh.is_winding_consistent}",
            "warning" if not new_mesh.is_winding_consistent else "info",
        )
    )

    # 2) 体量突变检查
    old_vol = float(old_mesh.volume) if old_mesh.is_volume else 0.0
    new_vol = float(new_mesh.volume) if new_mesh.is_volume else 0.0
    vol_ratio = _safe_ratio(abs(new_vol), abs(old_vol))

    if vol_ratio is None:
        checks.append(
            _make_item(
                "volume_change",
                True,
                f"volume ratio skipped because old volume is too small (old={old_vol:.6f}, new={new_vol:.6f})",
            )
        )
    else:
        passed = 0.2 <= vol_ratio <= 5.0
        checks.append(
            _make_item(
                "volume_change",
                passed,
                f"old_volume={old_vol:.3f}, new_volume={new_vol:.3f}, ratio={vol_ratio:.3f}",
                "warning" if not passed else "info",
            )
        )

    # 3) 主轴长度突变检查
    old_len = _extent_along_axis(old_mesh, primary_axis)
    new_len = _extent_along_axis(new_mesh, primary_axis)
    len_ratio = _safe_ratio(new_len, old_len)

    if len_ratio is None:
        checks.append(
            _make_item(
                "primary_axis_extent",
                True,
                f"extent ratio skipped because old extent is too small (old={old_len:.6f}, new={new_len:.6f})",
            )
        )
    else:
        if op in {"stretch", "scale"}:
            passed = 0.5 <= len_ratio <= 3.0
        else:
            passed = 0.2 <= len_ratio <= 5.0

        checks.append(
            _make_item(
                "primary_axis_extent",
                passed,
                f"old_extent={old_len:.3f}, new_extent={new_len:.3f}, ratio={len_ratio:.3f}",
                "warning" if not passed else "info",
            )
        )

    # 4) 邻接件碰撞 / 间隙检查（AABB 最小版）
    if neighbor_ids:
        collision_hits: List[str] = []
        clearance_hits: List[str] = []

        for neighbor_id in neighbor_ids:
            neighbor_path = part_to_file.get(neighbor_id)
            if neighbor_path is None or not Path(neighbor_path).exists():
                continue

            try:
                neighbor_mesh = _load_mesh(neighbor_path)
                collision, gap = _aabb_collision_and_gap(new_mesh, neighbor_mesh)

                if collision:
                    collision_hits.append(neighbor_id)
                elif gap < clearance_min_mm:
                    clearance_hits.append(f"{neighbor_id}:{gap:.3f}mm")
            except Exception as exc:
                warnings.append(f"neighbor check skipped for {neighbor_id}: {exc}")

        checks.append(
            _make_item(
                "collision",
                len(collision_hits) == 0,
                "no AABB collision with neighbors"
                if not collision_hits
                else f"AABB collision with neighbors: {', '.join(collision_hits)}",
                "error" if collision_hits else "info",
            )
        )

        checks.append(
            _make_item(
                "clearance",
                len(clearance_hits) == 0,
                "neighbor clearance looks acceptable"
                if not clearance_hits
                else f"neighbors below clearance_min_mm={clearance_min_mm}: {', '.join(clearance_hits)}",
                "warning" if clearance_hits else "info",
            )
        )
    else:
        checks.append(
            _make_item(
                "collision",
                True,
                "no neighbors configured, collision check skipped",
            )
        )
        checks.append(
            _make_item(
                "clearance",
                True,
                "no neighbors configured, clearance check skipped",
            )
        )

    # 5) 对称组一致性检查
    symmetry_mates = _get_symmetry_mates(part_constraints, part_id, symmetry_group)
    if symmetry_mates:
        mate_failures: List[str] = []
        new_extents = np.asarray(new_mesh.extents, dtype=float)

        for mate_id in symmetry_mates:
            mate_path = part_to_file.get(mate_id)
            if mate_path is None or not Path(mate_path).exists():
                continue

            try:
                mate_mesh = _load_mesh(mate_path)
                mate_extents = np.asarray(mate_mesh.extents, dtype=float)

                ratios = []
                for a, b in zip(new_extents.tolist(), mate_extents.tolist()):
                    r = _safe_ratio(max(a, b), min(a, b)) if min(a, b) > 1e-9 else None
                    if r is not None:
                        ratios.append(r)

                max_ratio = max(ratios) if ratios else 1.0
                if max_ratio > 1.5:
                    mate_failures.append(f"{mate_id}:extent_ratio={max_ratio:.3f}")
            except Exception as exc:
                warnings.append(f"symmetry check skipped for {mate_id}: {exc}")

        checks.append(
            _make_item(
                "symmetry_group",
                len(mate_failures) == 0,
                "symmetry mates look consistent"
                if not mate_failures
                else f"symmetry mismatch: {', '.join(mate_failures)}",
                "warning" if mate_failures else "info",
            )
        )
    else:
        checks.append(
            _make_item(
                "symmetry_group",
                True,
                "no symmetry mates configured, symmetry check skipped",
            )
        )

    failed_error = any((not x.passed) and x.severity == "error" for x in checks)
    failed_warning = any((not x.passed) and x.severity != "error" for x in checks)

    if failed_error:
        status = "warning"
        summary = "reasonableness check found high-risk issues"
    elif failed_warning:
        status = "warning"
        summary = "reasonableness check found minor issues"
    else:
        status = "pass"
        summary = "reasonableness check passed"

    return ReasonablenessReport(
        part_id=part_id,
        op=op,
        input_path=input_path,
        output_path=output_path,
        status=status,
        checks=[asdict(x) for x in checks],
        warnings=warnings,
        summary=summary,
    )


def report_to_dict(report: ReasonablenessReport) -> Dict[str, Any]:
    return asdict(report)