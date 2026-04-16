from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import trimesh


@dataclass
class AnchorComputation:
    anchor_mode: str
    anchor_point: List[float]
    axis_used: List[float]
    detail: str = ""


class GeometryAnchorService:
    """
    几何锚点与主轴辅助服务。

    这版专门针对你当前 part_constraints.json 的生成脚本做了兼容：
    - 优先使用 geometry.center_mass / geometry.bbox_center 作为 hint
    - 若 hint 不可用，再回退到 mesh.bounds / mesh.center
    - 当前先服务 transform_with_constraints，后续可直接复用到 add_with_attachment
    """

    def load_mesh(self, stl_path: str | Path) -> trimesh.Trimesh:
        mesh = trimesh.load_mesh(stl_path, process=False)
        if isinstance(mesh, trimesh.Scene):
            if len(mesh.geometry) == 0:
                raise ValueError(f"No geometry in scene: {stl_path}")
            mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
        if not isinstance(mesh, trimesh.Trimesh):
            raise TypeError(f"Loaded object is not a Trimesh: {type(mesh)}")
        if len(mesh.vertices) == 0:
            raise ValueError(f"Mesh has no vertices: {stl_path}")
        return mesh.copy()

    def save_mesh(self, mesh: trimesh.Trimesh, output_path: str | Path) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(output_path)
        return str(output_path)

    def normalize_axis(self, axis: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(axis), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid axis: {axis}")
        return arr / norm

    def _to_valid_vec3(self, value: Optional[Iterable[float]]) -> Optional[np.ndarray]:
        if value is None:
            return None
        try:
            arr = np.asarray(list(value), dtype=float).reshape(3)
            if not np.all(np.isfinite(arr)):
                return None
            return arr
        except Exception:
            return None

    def mesh_bounds_center(self, mesh: trimesh.Trimesh) -> np.ndarray:
        bounds = mesh.bounds
        return (bounds[0] + bounds[1]) / 2.0

    def preferred_center(
        self,
        mesh: trimesh.Trimesh,
        center_mass_hint: Optional[Iterable[float]] = None,
        bbox_center_hint: Optional[Iterable[float]] = None,
    ) -> tuple[np.ndarray, str]:
        cm = self._to_valid_vec3(center_mass_hint)
        if cm is not None:
            return cm, "use geometry.center_mass hint"

        bc = self._to_valid_vec3(bbox_center_hint)
        if bc is not None:
            return bc, "use geometry.bbox_center hint"

        return self.mesh_bounds_center(mesh), "use mesh bounds center fallback"

    def mesh_extent_along_axis(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self.normalize_axis(axis)
        projections = np.dot(mesh.vertices, axis_vec)
        return float(projections.max() - projections.min())

    def end_point_along_axis(
        self,
        mesh: trimesh.Trimesh,
        axis: Iterable[float],
        use_min_end: bool = True,
        center_hint: Optional[Iterable[float]] = None,
    ) -> tuple[np.ndarray, str]:
        axis_vec = self.normalize_axis(axis)
        center = self._to_valid_vec3(center_hint)
        if center is None:
            center = self.mesh_bounds_center(mesh)
            center_source = "mesh bounds center"
        else:
            center_source = "preferred center hint"

        projections = np.dot(mesh.vertices, axis_vec)
        target_proj = float(projections.min() if use_min_end else projections.max())
        current_proj = float(np.dot(center, axis_vec))
        delta = target_proj - current_proj
        anchor = center + delta * axis_vec
        detail = f"use {'min' if use_min_end else 'max'} projection end along axis; center={center_source}"
        return anchor, detail

    def get_anchor_point(
        self,
        mesh: trimesh.Trimesh,
        anchor_mode: str,
        primary_axis: Iterable[float],
        center_mass_hint: Optional[Iterable[float]] = None,
        bbox_center_hint: Optional[Iterable[float]] = None,
    ) -> AnchorComputation:
        axis_vec = self.normalize_axis(primary_axis)
        preferred_center, center_detail = self.preferred_center(
            mesh,
            center_mass_hint=center_mass_hint,
            bbox_center_hint=bbox_center_hint,
        )

        mode = (anchor_mode or "center").strip()

        if mode in {"center", ""}:
            return AnchorComputation(
                anchor_mode="center",
                anchor_point=preferred_center.tolist(),
                axis_used=axis_vec.tolist(),
                detail=f"{center_detail}; anchor=center",
            )

        if mode == "none":
            return AnchorComputation(
                anchor_mode="none",
                anchor_point=preferred_center.tolist(),
                axis_used=axis_vec.tolist(),
                detail=f"{center_detail}; anchor_mode none fallback to center",
            )

        if mode == "axis_fixed":
            return AnchorComputation(
                anchor_mode="axis_fixed",
                anchor_point=preferred_center.tolist(),
                axis_used=axis_vec.tolist(),
                detail=f"{center_detail}; anchor=axis_fixed(center-like)",
            )

        if mode == "parent_attach":
            # 当前先保守实现为中心锚定；未来 add_with_attachment 可在这里扩展成真正安装面逻辑
            return AnchorComputation(
                anchor_mode="parent_attach",
                anchor_point=preferred_center.tolist(),
                axis_used=axis_vec.tolist(),
                detail=f"{center_detail}; parent_attach currently fallback to preferred center",
            )

        if mode == "base_face_fixed":
            anchor, detail = self.end_point_along_axis(
                mesh=mesh,
                axis=axis_vec,
                use_min_end=True,
                center_hint=preferred_center,
            )
            return AnchorComputation(
                anchor_mode="base_face_fixed",
                anchor_point=anchor.tolist(),
                axis_used=axis_vec.tolist(),
                detail=detail,
            )

        return AnchorComputation(
            anchor_mode="fallback_center",
            anchor_point=preferred_center.tolist(),
            axis_used=axis_vec.tolist(),
            detail=f"{center_detail}; unknown anchor_mode={mode}, fallback to center",
        )

    def axis_name_to_vector(self, axis_name: str) -> np.ndarray:
        axis_name = str(axis_name).lower().strip()
        if axis_name == "x":
            return np.asarray([1.0, 0.0, 0.0], dtype=float)
        if axis_name == "y":
            return np.asarray([0.0, 1.0, 0.0], dtype=float)
        if axis_name == "z":
            return np.asarray([0.0, 0.0, 1.0], dtype=float)
        raise ValueError(f"Unsupported axis name: {axis_name}")