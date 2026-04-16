from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional

import numpy as np
import trimesh

from app.models import SkillExecutionResult
from app.services.geometry_anchor_service import GeometryAnchorService
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

    本版修订重点：
    1. 对齐你现在的 part_constraints.json 生成脚本；
    2. 锚点计算统一交给 GeometryAnchorService；
    3. 优先使用 geometry.center_mass / geometry.bbox_center；
    4. 仍保持 demo 级最小实现，不引入复杂局部重构。
    """

    def __init__(
        self,
        constraint_service: PartConstraintService,
        anchor_service: Optional[GeometryAnchorService] = None,
    ) -> None:
        self.constraint_service = constraint_service
        self.anchor_service = anchor_service or GeometryAnchorService()

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
        axis = self.anchor_service.normalize_axis(axis)
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be > 0, got {scale_factor}")

        u = axis.reshape(3, 1)
        linear = np.eye(3) + (scale_factor - 1.0) * (u @ u.T)

        mat = np.eye(4, dtype=float)
        mat[:3, :3] = linear

        t1 = np.eye(4, dtype=float)
        t1[:3, 3] = -anchor_point

        t2 = np.eye(4, dtype=float)
        t2[:3, 3] = anchor_point

        return t2 @ mat @ t1

    def _resolve_anchor(self, mesh: trimesh.Trimesh, part_id: str) -> tuple[np.ndarray, np.ndarray, str]:
        axis = self.constraint_service.get_primary_axis(part_id)
        anchor_mode = self.constraint_service.get_anchor_mode(part_id)
        geometry_hint = self.constraint_service.get_geometry_hint(part_id)

        anchor_info = self.anchor_service.get_anchor_point(
            mesh=mesh,
            anchor_mode=anchor_mode,
            primary_axis=axis,
            center_mass_hint=geometry_hint.center_mass or None,
            bbox_center_hint=geometry_hint.bbox_center or None,
        )
        return (
            np.asarray(anchor_info.anchor_point, dtype=float),
            np.asarray(anchor_info.axis_used, dtype=float),
            anchor_info.detail,
        )

    def constrained_translate(
        self,
        part_id: str,
        stl_path: str | Path,
        output_path: str | Path,
        offset_xyz_mm: List[float],
    ) -> TransformResult:
        self.constraint_service.assert_operation_allowed(part_id, "translate")

        mesh = self.anchor_service.load_mesh(stl_path)
        offset = np.asarray(offset_xyz_mm, dtype=float).reshape(3)
        transform = self._make_translation_matrix(offset)
        mesh.apply_transform(transform)
        saved = self.anchor_service.save_mesh(mesh, output_path)

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

        mesh = self.anchor_service.load_mesh(stl_path)
        anchor_point, default_axis, anchor_detail = self._resolve_anchor(mesh, part_id)
        axis_used = self.anchor_service.normalize_axis(axis or default_axis)
        transform = self._make_rotation_matrix(
            angle_deg=angle_deg,
            axis=axis_used,
            anchor_point=anchor_point,
        )
        mesh.apply_transform(transform)
        saved = self.anchor_service.save_mesh(mesh, output_path)

        return TransformResult(
            success=True,
            operation="rotate",
            part_id=part_id,
            output_path=saved,
            detail=f"Rotated by {angle_deg} deg; {anchor_detail}",
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
        self.constraint_service.assert_operation_allowed(part_id, "stretch")

        mesh = self.anchor_service.load_mesh(stl_path)
        anchor_point, default_axis, anchor_detail = self._resolve_anchor(mesh, part_id)
        axis_used = self.anchor_service.normalize_axis(axis or default_axis)

        old_len = self.anchor_service.mesh_extent_along_axis(mesh, axis_used)
        if old_len <= 1e-6:
            raise ValueError(f"Mesh extent along axis too small: {old_len}")

        new_len = old_len + float(delta_mm)
        if new_len <= 1e-6:
            raise ValueError(f"Stretch result length too small: new_len={new_len}")

        scale_factor = new_len / old_len
        transform = self._make_stretch_matrix_with_anchor(
            scale_factor=scale_factor,
            axis=axis_used,
            anchor_point=anchor_point,
        )
        mesh.apply_transform(transform)
        saved = self.anchor_service.save_mesh(mesh, output_path)

        return TransformResult(
            success=True,
            operation="stretch",
            part_id=part_id,
            output_path=saved,
            detail=(
                f"Stretched along axis by delta_mm={delta_mm}, "
                f"old_len={old_len:.3f}, new_len={new_len:.3f}; {anchor_detail}"
            ),
            anchor_point=anchor_point.tolist(),
            axis_used=axis_used.tolist(),
            transform_matrix=transform.tolist(),
        )


def transform_result_to_skill_execution(result: TransformResult) -> SkillExecutionResult:
    warnings: List[str] = []
    if result.anchor_point is not None:
        warnings.append(f"anchor_point={result.anchor_point}")
    if result.axis_used is not None:
        warnings.append(f"axis_used={result.axis_used}")

    return SkillExecutionResult(
        success=result.success,
        output_files=[result.output_path] if result.output_path else [],
        warnings=warnings,
        message=result.detail,
        target_part=result.part_id,
        op=result.operation,
    )