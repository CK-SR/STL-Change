from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import trimesh

from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService


@dataclass
class AddFitResult:
    success: bool
    output_path: str
    fit_plan: Dict[str, Any]
    message: str
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AddFitService:
    """
    对新增件做“本地几何拟合”：
    1) 解析导入 STL 的主轴 / bbox / 底面
    2) 读取 attach_to 对应已有部件的几何与约束
    3) 通过规则求出粗旋转、中心对齐、底面对齐、可选伸长
    4) 应用少量覆写 post_transform_overrides
    """

    def __init__(
        self,
        *,
        anchor_service: Optional[GeometryAnchorService] = None,
        constraint_service: Optional[PartConstraintService] = None,
    ) -> None:
        self.anchor_service = anchor_service or GeometryAnchorService()
        self.constraint_service = constraint_service

    def _normalize(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _mesh_bounds_center(self, mesh: trimesh.Trimesh) -> np.ndarray:
        b = mesh.bounds
        return (b[0] + b[1]) / 2.0

    def _principal_axes(self, mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
        verts = np.asarray(mesh.vertices, dtype=float)
        center = verts.mean(axis=0)
        centered = verts - center
        cov = np.cov(centered.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        eigvals = eigvals[order]
        eigvecs = eigvecs[:, order]

        axes = eigvecs.T
        lengths = []
        for axis in axes:
            proj = centered @ axis
            lengths.append(float(proj.max() - proj.min()))
        return axes, np.asarray(lengths, dtype=float)

    def _rotation_matrix_align_vectors(
        self,
        src: np.ndarray,
        dst: np.ndarray,
        point: np.ndarray,
    ) -> np.ndarray:
        src = self._normalize(src)
        dst = self._normalize(dst)

        dot = float(np.clip(np.dot(src, dst), -1.0, 1.0))
        if abs(dot - 1.0) < 1e-8:
            return np.eye(4, dtype=float)

        if abs(dot + 1.0) < 1e-8:
            helper = np.asarray([1.0, 0.0, 0.0], dtype=float)
            if abs(np.dot(helper, src)) > 0.9:
                helper = np.asarray([0.0, 1.0, 0.0], dtype=float)
            axis = np.cross(src, helper)
            axis = self._normalize(axis)
            return trimesh.transformations.rotation_matrix(
                angle=math.pi,
                direction=axis,
                point=point,
            )

        axis = np.cross(src, dst)
        axis = self._normalize(axis)
        angle = math.acos(dot)
        return trimesh.transformations.rotation_matrix(
            angle=angle,
            direction=axis,
            point=point,
        )

    def _stretch_matrix_about_point(
        self,
        *,
        axis: np.ndarray,
        scale_factor: float,
        anchor_point: np.ndarray,
    ) -> np.ndarray:
        axis = self._normalize(axis)
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

    def _extent_along_axis(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self._normalize(axis)
        projections = np.dot(mesh.vertices, axis_vec)
        return float(projections.max() - projections.min())

    def _default_coverage_ratio(self, category: str) -> float:
        c = (category or "").strip().lower()
        if c in {"roof", "cage", "guard", "frame"}:
            return 0.92
        if c in {"sensor", "pod"}:
            return 1.0
        return 0.9

    def _default_allow_stretch(self, category: str) -> bool:
        c = (category or "").strip().lower()
        return c in {"roof", "cage", "guard", "frame"}

    def _find_attach_axis(self, attach_to: str) -> np.ndarray:
        if self.constraint_service is None:
            return np.asarray([1.0, 0.0, 0.0], dtype=float)

        try:
            return np.asarray(self.constraint_service.get_primary_axis(attach_to), dtype=float)
        except Exception:
            return np.asarray([1.0, 0.0, 0.0], dtype=float)

    def _find_clearance(self, attach_to: str, fit_policy: Dict[str, Any]) -> float:
        if fit_policy.get("clearance_mm") is not None:
            return float(fit_policy["clearance_mm"])

        if self.constraint_service is not None:
            try:
                return float(self.constraint_service.get_clearance_min_mm(attach_to))
            except Exception:
                pass

        return 5.0

    def fit_imported_asset(
        self,
        *,
        imported_stl_path: str | Path,
        attach_to: str,
        attach_to_path: str | Path,
        output_path: str | Path,
        asset_metadata: Dict[str, Any] | None = None,
        fit_policy: Dict[str, Any] | None = None,
        post_transform_overrides: Dict[str, Any] | None = None,
    ) -> AddFitResult:
        fit_policy = fit_policy or {}
        post_transform_overrides = post_transform_overrides or {}
        asset_metadata = asset_metadata or {}
        warnings: List[str] = []

        try:
            imported_mesh = self.anchor_service.load_mesh(imported_stl_path)
            parent_mesh = self.anchor_service.load_mesh(attach_to_path)
        except Exception as exc:
            return AddFitResult(
                success=False,
                output_path="",
                fit_plan={},
                message=f"load mesh failed: {exc}",
                warnings=warnings,
            )

        work_mesh = imported_mesh.copy()
        imported_center = self._mesh_bounds_center(work_mesh)
        parent_center = self._mesh_bounds_center(parent_mesh)
        parent_bounds = parent_mesh.bounds

        attach_axis = self._find_attach_axis(attach_to)
        attach_axis_xy = np.asarray([attach_axis[0], attach_axis[1], 0.0], dtype=float)
        if np.linalg.norm(attach_axis_xy) < 1e-9:
            attach_axis_xy = np.asarray([1.0, 0.0, 0.0], dtype=float)
        attach_axis_xy = self._normalize(attach_axis_xy)

        axes, lengths = self._principal_axes(work_mesh)
        long_axis = axes[0]
        thin_axis = axes[-1]

        # 第一步：薄轴对齐 Z
        rot1 = self._rotation_matrix_align_vectors(
            thin_axis,
            np.asarray([0.0, 0.0, 1.0], dtype=float),
            imported_center,
        )
        work_mesh.apply_transform(rot1)

        # 第二步：长轴对齐挂载主轴（仅考虑水平投影）
        axes2, _ = self._principal_axes(work_mesh)
        long_axis_2 = np.asarray(axes2[0], dtype=float)
        long_axis_2_xy = np.asarray([long_axis_2[0], long_axis_2[1], 0.0], dtype=float)
        if np.linalg.norm(long_axis_2_xy) < 1e-9:
            long_axis_2_xy = np.asarray([1.0, 0.0, 0.0], dtype=float)
        long_axis_2_xy = self._normalize(long_axis_2_xy)

        imported_center_2 = self._mesh_bounds_center(work_mesh)
        rot2 = self._rotation_matrix_align_vectors(
            long_axis_2_xy,
            attach_axis_xy,
            imported_center_2,
        )
        work_mesh.apply_transform(rot2)

        category = str(asset_metadata.get("category", "")).strip().lower()
        coverage_ratio = float(
            fit_policy.get("coverage_ratio", self._default_coverage_ratio(category))
        )
        allow_stretch = bool(
            fit_policy.get("allow_stretch", self._default_allow_stretch(category))
        )
        clearance_mm = self._find_clearance(attach_to, fit_policy)

        # 可选 stretch：沿 attach_axis 做覆盖式拟合
        stretch_delta_mm = 0.0
        if allow_stretch:
            try:
                old_len = self._extent_along_axis(work_mesh, attach_axis_xy)
                parent_len = self._extent_along_axis(parent_mesh, attach_axis_xy)
                target_len = parent_len * coverage_ratio

                if old_len > 1e-6 and target_len > 1e-6:
                    scale_factor = target_len / old_len
                    stretch_delta_mm = target_len - old_len

                    stretch_anchor = self._mesh_bounds_center(work_mesh)
                    stretch_mat = self._stretch_matrix_about_point(
                        axis=attach_axis_xy,
                        scale_factor=scale_factor,
                        anchor_point=stretch_anchor,
                    )
                    work_mesh.apply_transform(stretch_mat)
            except Exception as exc:
                warnings.append(f"auto stretch skipped: {exc}")

        # 平移：x/y 居中，底面对齐到 parent 顶面之上
        work_bounds = work_mesh.bounds
        work_center = self._mesh_bounds_center(work_mesh)

        translate_vec = np.asarray(
            [
                float(parent_center[0] - work_center[0]),
                float(parent_center[1] - work_center[1]),
                float(parent_bounds[1][2] - work_bounds[0][2] + clearance_mm),
            ],
            dtype=float,
        )

        trans_mat = np.eye(4, dtype=float)
        trans_mat[:3, 3] = translate_vec
        work_mesh.apply_transform(trans_mat)

        fit_plan: Dict[str, Any] = {
            "attach_to": attach_to,
            "category": category,
            "coverage_ratio": coverage_ratio,
            "allow_stretch": allow_stretch,
            "clearance_mm": clearance_mm,
            "auto_translate": {
                "x": float(translate_vec[0]),
                "y": float(translate_vec[1]),
                "z": float(translate_vec[2]),
            },
            "auto_rotation": {
                "thin_axis_to_z": True,
                "long_axis_to_parent_primary_axis": True,
            },
            "auto_stretch_delta_mm": float(stretch_delta_mm),
        }

        # 覆写：只做轻量附加变换
        overrides_applied: Dict[str, Any] = {}

        translate_override = post_transform_overrides.get("translate")
        if isinstance(translate_override, dict):
            dx = float(translate_override.get("x", 0.0))
            dy = float(translate_override.get("y", 0.0))
            dz = float(translate_override.get("z", 0.0))
            extra_t = np.eye(4, dtype=float)
            extra_t[:3, 3] = np.asarray([dx, dy, dz], dtype=float)
            work_mesh.apply_transform(extra_t)
            overrides_applied["translate"] = {"x": dx, "y": dy, "z": dz}

        rotate_override = post_transform_overrides.get("rotate")
        if isinstance(rotate_override, dict):
            degrees = float(rotate_override.get("degrees", 0.0))
            axis_name = str(rotate_override.get("axis", "z")).strip().lower()
            if axis_name == "x":
                axis_vec = np.asarray([1.0, 0.0, 0.0], dtype=float)
            elif axis_name == "y":
                axis_vec = np.asarray([0.0, 1.0, 0.0], dtype=float)
            else:
                axis_vec = np.asarray([0.0, 0.0, 1.0], dtype=float)

            rot = trimesh.transformations.rotation_matrix(
                angle=math.radians(degrees),
                direction=axis_vec,
                point=self._mesh_bounds_center(work_mesh),
            )
            work_mesh.apply_transform(rot)
            overrides_applied["rotate"] = {"axis": axis_name, "degrees": degrees}

        stretch_override = post_transform_overrides.get("stretch")
        if isinstance(stretch_override, dict):
            delta_mm = float(stretch_override.get("delta_mm", 0.0))
            if abs(delta_mm) > 1e-6:
                current_len = self._extent_along_axis(work_mesh, attach_axis_xy)
                target_len = current_len + delta_mm
                if target_len > 1e-6 and current_len > 1e-6:
                    factor = target_len / current_len
                    extra_s = self._stretch_matrix_about_point(
                        axis=attach_axis_xy,
                        scale_factor=factor,
                        anchor_point=self._mesh_bounds_center(work_mesh),
                    )
                    work_mesh.apply_transform(extra_s)
                    overrides_applied["stretch"] = {"delta_mm": delta_mm}

        if overrides_applied:
            fit_plan["overrides_applied"] = overrides_applied

        try:
            saved = self.anchor_service.save_mesh(work_mesh, output_path)
        except Exception as exc:
            return AddFitResult(
                success=False,
                output_path="",
                fit_plan=fit_plan,
                message=f"save fitted mesh failed: {exc}",
                warnings=warnings,
            )

        return AddFitResult(
            success=True,
            output_path=saved,
            fit_plan=fit_plan,
            message="imported asset fitted and saved",
            warnings=warnings,
        )