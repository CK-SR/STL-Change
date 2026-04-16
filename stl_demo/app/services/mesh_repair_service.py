from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List

import trimesh
from trimesh import repair as trimesh_repair


@dataclass
class MeshRepairRecord:
    input_path: str
    output_path: str
    success: bool
    actions: List[str]
    warnings: List[str]
    stats_before: Dict[str, Any]
    stats_after: Dict[str, Any]
    message: str = ""


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


def _mesh_stats(mesh: trimesh.Trimesh) -> Dict[str, Any]:
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        "euler_number": int(mesh.euler_number) if mesh.euler_number is not None else None,
    }


def repair_mesh(
    mesh: trimesh.Trimesh,
    enable_light_remesh: bool = False,
) -> tuple[trimesh.Trimesh, MeshRepairRecord]:
    actions: List[str] = []
    warnings: List[str] = []

    before = _mesh_stats(mesh)
    repaired = mesh.copy()

    try:
        trimesh_repair.fix_normals(repaired)
        actions.append("fix_normals")
    except Exception as exc:
        warnings.append(f"fix_normals failed: {exc}")

    try:
        trimesh_repair.fix_winding(repaired)
        actions.append("fix_winding")
    except Exception as exc:
        warnings.append(f"fix_winding failed: {exc}")

    try:
        removed = repaired.remove_duplicate_faces()
        actions.append("remove_duplicate_faces")
        if removed is not None:
            warnings.append(f"duplicate_faces_removed={removed}")
    except Exception as exc:
        warnings.append(f"remove_duplicate_faces failed: {exc}")

    try:
        repaired.remove_unreferenced_vertices()
        actions.append("remove_unreferenced_vertices")
    except Exception as exc:
        warnings.append(f"remove_unreferenced_vertices failed: {exc}")

    # Day3 第一版默认不开
    if enable_light_remesh:
        warnings.append("light_remesh requested but not enabled in minimal Day3 implementation")

    after = _mesh_stats(repaired)

    record = MeshRepairRecord(
        input_path="",
        output_path="",
        success=True,
        actions=actions,
        warnings=warnings,
        stats_before=before,
        stats_after=after,
        message="mesh repair finished",
    )
    return repaired, record


def repair_mesh_file(
    path: str | Path,
    overwrite: bool = True,
    enable_light_remesh: bool = False,
) -> MeshRepairRecord:
    path = Path(path)
    mesh = _load_mesh(path)
    repaired, record = repair_mesh(mesh, enable_light_remesh=enable_light_remesh)

    output_path = path if overwrite else path.with_name(f"{path.stem}_repaired{path.suffix}")
    repaired.export(output_path)

    record.input_path = str(path)
    record.output_path = str(output_path)
    return record


def record_to_dict(record: MeshRepairRecord) -> Dict[str, Any]:
    return asdict(record)