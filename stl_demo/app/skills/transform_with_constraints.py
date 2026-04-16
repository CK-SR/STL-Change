from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import numpy as np
import trimesh

from app.services.part_constraint_service import PartConstraintService


OperationName = Literal["translate", "rotate", "stretch"]


@dataclass
class TransformResult:
    success: bool
    operation: str
    part_id: str
    output_path: Optional[str]
    detail: str
    anchor_point: Optional[List[float]] = None
    axis_used: Optional[List[float]] = None
    transform_matrix: Optional[List[List[float]]] = None


class TransformWithConstraints:
    """
    受约束几何编辑最小版：
    - constrained_translate
    - anchored_rotate
    - constrained_stretch

    说明：
    1. 这版优先服务 demo，不追求 CAD 级精确。
    2. stretch 当前采用“沿主轴单轴缩放 + 锚点固定”的方式。
    3. 后续可以在此基础上继续接 mesh_repair_service / reasonableness_checker。
    """

    def __init__(self, constraint_service: PartConstraintService) -> None:
        self.constraint_service = constraint_service

    # =========================
    # 公共工具
    # =========================
    def _load_mesh(self, stl_path: str | Path) -> trimesh.Trimesh:
        mesh = trimesh.load_mesh(stl_path, process=False)

        if isinstance(mesh, trimesh.Scene):
            if len(mesh.geometry) == 0:
                raise ValueError(f"No geometry in scene: {stl_path}")
            mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

        if not isinstance(mesh, trimesh.Trimesh):
            raise TypeError(f"Loaded object is not a mesh: {type(mesh)}")

        if len(mesh.vertices) == 0:
            raise ValueError(f"Mesh has no vertices: {stl_path}")

        return mesh.copy()

    def _save_mesh(self, mesh: trimesh.Trimesh, output_path: str | Path) -> str:
        output_path = str(output_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        mesh.export(output_path)
        return output_path

    def _normalize_axis(self, axis: List[float] | np.ndarray) -> np.ndarray:
        arr = np.asarray(axis, dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid axis: {axis}")
        return arr / norm

    def _get_anchor_point(self, mesh: trimesh.Trimesh, part_id: str) -> np.ndarray:
        """
        根据 anchor_mode 选一个最小可用锚点。
        当前支持：
        - center
        - base_face_fixed
        - axis_fixed
        - none -> fallback center
        """
        anchor_mode = self.constraint_service.get_anchor_mode(part_id)
        bbox = mesh.bounds
        min_bound = bbox[0]
        max_bound = bbox[1]
        center = (min_bound + max_bound) / 2.0

        if anchor_mode == "center":
            return center

        if anchor_mode == "none":
            return center

        if anchor_mode == "axis_fixed":
            # 当前最小版先退化为中心点
            return center

        if anchor_mode == "base_face_fixed":
            axis = self._normalize_axis(self.constraint_service.get_primary_axis(part_id))
            dots_min = np.dot(min_bound, axis)
            dots_max = np.dot(max_bound, axis)

            # 选择沿主轴较小一端作为“基座侧”
            base_proj = min(dots_min, dots_max)
            base_point = center.copy()

            # 用 center 投影回 base 端附近
            current_proj = np.dot(center, axis)
            delta = base_proj - current_proj
            base_point = center + delta * axis
            return base_point

        return center

    def _make_translation_matrix(self, offset: np.ndarray) -> np.ndarray:
        mat = np.eye(4, dtype=float)
        mat[:3, 3] = offset[:3]
        return mat

    def _make_rotation_matrix(
        self,
        angle_deg: float,
        axis: np.ndarray,
        anchor_point: np.ndarray,
    ) -> np.ndarray:
        angle_rad = math.radians(angle_deg)
        rot = trimesh.transformations.rotation_matrix(
            angle=angle_rad,
            direction=axis,
            point=anchor_point,
        )
        return np.asarray(rot, dtype=float)

    def _make_stretch_matrix_with_anchor(
        self,
        scale_factor: float,
        axis: np.ndarray,
        anchor_point: np.ndarray,
    ) -> np.ndarray:
        """
        沿指定轴单轴缩放，并保持 anchor_point 不动。
        公式：
        M = T(anchor) * S_axis * T(-anchor)
        """
        axis = self._normalize_axis(axis)
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be > 0, got {scale_factor}")

        # 单轴缩放矩阵：
        # S = I + (s - 1) * (u u^T)
        u = axis.reshape(3, 1)
        linear = np.eye(3) + (scale_factor - 1.0) * (u @ u.T)

        mat = np.eye(4, dtype=float)
        mat[:3, :3] = linear

        t1 = np.eye(4, dtype=float)
        t1[:3, 3] = -anchor_point

        t2 = np.eye(4, dtype=float)
        t2[:3, 3] = anchor_point

        return t2 @ mat @ t1

    def _mesh_extent_along_axis(self, mesh: trimesh.Trimesh, axis: np.ndarray) -> float:
        axis = self._normalize_axis(axis)
        projections = np.dot(mesh.vertices, axis)
        return float(projections.max() - projections.min())

    # =========================
    # 对外方法
    # =========================
    def constrained_translate(
        self,
        part_id: str,
        stl_path: str | Path,
        output_path: str | Path,
        offset_xyz_mm: List[float],
    ) -> TransformResult:
        self.constraint_service.assert_operation_allowed(part_id, "translate")

        mesh = self._load_mesh(stl_path)
        offset = np.asarray(offset_xyz_mm, dtype=float).reshape(3)
        transform = self._make_translation_matrix(offset)

        mesh.apply_transform(transform)
        saved = self._save_mesh(mesh, output_path)

        return TransformResult(
            success=True,
            operation="translate",
            part_id=part_id,
            output_path=saved,
            detail=f"Translated by offset={offset.tolist()}",
            transform_matrix=transform.tolist(),
        )

    def anchored_rotate(
        self,
        part_id: str,
        stl_path: str | Path,
        output_path: str | Path,
        angle_deg: float,
        axis: Optional[List[float]] = None,
    ) -> TransformResult:
        self.constraint_service.assert_operation_allowed(part_id, "rotate")

        mesh = self._load_mesh(stl_path)
        axis_used = self._normalize_axis(axis or self.constraint_service.get_primary_axis(part_id))
        anchor_point = self._get_anchor_point(mesh, part_id)

        transform = self._make_rotation_matrix(
            angle_deg=angle_deg,
            axis=axis_used,
            anchor_point=anchor_point,
        )

        mesh.apply_transform(transform)
        saved = self._save_mesh(mesh, output_path)

        return TransformResult(
            success=True,
            operation="rotate",
            part_id=part_id,
            output_path=saved,
            detail=f"Rotated by {angle_deg} deg around anchor={anchor_point.tolist()}",
            anchor_point=anchor_point.tolist(),
            axis_used=axis_used.tolist(),
            transform_matrix=transform.tolist(),
        )

    def constrained_stretch(
        self,
        part_id: str,
        stl_path: str | Path,
        output_path: str | Path,
        delta_mm: float,
        axis: Optional[List[float]] = None,
    ) -> TransformResult:
        """
        将“整体 scale”改成“沿主轴单轴伸缩”。
        计算方式：
        - 先测量 mesh 在该轴方向上的当前长度 old_len
        - new_len = old_len + delta_mm
        - scale_factor = new_len / old_len
        - 保持 anchor_point 固定，沿主轴方向做单轴缩放
        """
        self.constraint_service.assert_operation_allowed(part_id, "stretch")

        mesh = self._load_mesh(stl_path)
        axis_used = self._normalize_axis(axis or self.constraint_service.get_primary_axis(part_id))
        anchor_point = self._get_anchor_point(mesh, part_id)

        old_len = self._mesh_extent_along_axis(mesh, axis_used)
        if old_len <= 1e-6:
            raise ValueError(f"Mesh extent along axis too small: {old_len}")

        new_len = old_len + float(delta_mm)
        if new_len <= 1e-6:
            raise ValueError(f"Invalid new length: {new_len}")

        scale_factor = new_len / old_len
        transform = self._make_stretch_matrix_with_anchor(
            scale_factor=scale_factor,
            axis=axis_used,
            anchor_point=anchor_point,
        )

        mesh.apply_transform(transform)
        saved = self._save_mesh(mesh, output_path)

        return TransformResult(
            success=True,
            operation="stretch",
            part_id=part_id,
            output_path=saved,
            detail=(
                f"Stretched along axis by delta_mm={delta_mm}, "
                f"old_len={old_len:.4f}, new_len={new_len:.4f}, scale_factor={scale_factor:.6f}"
            ),
            anchor_point=anchor_point.tolist(),
            axis_used=axis_used.tolist(),
            transform_matrix=transform.tolist(),
        )

    def run(
        self,
        operation: OperationName,
        part_id: str,
        stl_path: str | Path,
        output_path: str | Path,
        **kwargs: Any,
    ) -> TransformResult:
        if operation == "translate":
            return self.constrained_translate(
                part_id=part_id,
                stl_path=stl_path,
                output_path=output_path,
                offset_xyz_mm=kwargs["offset_xyz_mm"],
            )

        if operation == "rotate":
            return self.anchored_rotate(
                part_id=part_id,
                stl_path=stl_path,
                output_path=output_path,
                angle_deg=kwargs["angle_deg"],
                axis=kwargs.get("axis"),
            )

        if operation == "stretch":
            return self.constrained_stretch(
                part_id=part_id,
                stl_path=stl_path,
                output_path=output_path,
                delta_mm=kwargs["delta_mm"],
                axis=kwargs.get("axis"),
            )

        raise ValueError(f"Unsupported operation: {operation}")