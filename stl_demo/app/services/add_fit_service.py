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
    3) 先做“尺度归一化”，保证新增件与父件在同一量级
    4) 再做粗旋转、中心对齐、顶部挂载面对齐、可选有限拉伸
    5) 应用少量覆写 post_transform_overrides

    第三轮修订重点：
    - 修正“悬空”问题：
      不再使用 bbox 整体 top / bottom 做 Z 对齐
      改为估计：
        1) 父件顶部主平面高度
        2) 新增件底部安装基面高度
    - 对 roof/cage/guard/frame + cover_parent 仍优先按 XY footprint 做 uniform scale
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

    def _uniform_scale_matrix_about_point(
        self,
        *,
        scale_factor: float,
        anchor_point: np.ndarray,
    ) -> np.ndarray:
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be > 0, got {scale_factor}")

        mat = np.eye(4, dtype=float)
        mat[0, 0] = scale_factor
        mat[1, 1] = scale_factor
        mat[2, 2] = scale_factor

        t1 = np.eye(4, dtype=float)
        t1[:3, 3] = -anchor_point

        t2 = np.eye(4, dtype=float)
        t2[:3, 3] = anchor_point

        return t2 @ mat @ t1

    def _extent_along_axis(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self._normalize(axis)
        projections = np.dot(mesh.vertices, axis_vec)
        return float(projections.max() - projections.min())

    def _safe_extents(self, mesh: trimesh.Trimesh) -> np.ndarray:
        extents = np.asarray(mesh.extents, dtype=float).reshape(3)
        extents = np.where(np.isfinite(extents), extents, 0.0)
        return extents

    def _xy_extents(self, mesh: trimesh.Trimesh) -> tuple[float, float]:
        ext = self._safe_extents(mesh)
        return float(ext[0]), float(ext[1])

    def _default_coverage_ratio(self, category: str) -> float:
        c = (category or "").strip().lower()
        if c in {"roof", "cage", "guard", "frame"}:
            return 0.92
        if c in {"sensor", "pod", "radar", "antenna"}:
            return 0.35
        return 0.9

    def _default_allow_stretch(self, category: str) -> bool:
        c = (category or "").strip().lower()
        return c in {"roof", "cage", "guard", "frame", "sensor", "pod", "radar", "antenna"}

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

    def _get_fit_mode(self, fit_policy: Dict[str, Any]) -> str:
        mode = str(fit_policy.get("mode", "bounded_fit")).strip().lower()
        if mode not in {"keep_original", "bounded_fit", "cover_parent"}:
            return "bounded_fit"
        return mode

    def _default_visual_ratio_range(self, category: str) -> tuple[float, float]:
        c = (category or "").strip().lower()
        if c in {"sensor", "radar", "antenna"}:
            return 0.08, 0.22
        if c in {"pod"}:
            return 0.10, 0.28
        if c in {"roof", "cage", "guard", "frame"}:
            return 0.55, 0.95
        return 0.10, 0.35

    def _is_large_cover_part(self, category: str) -> bool:
        c = (category or "").strip().lower()
        return c in {"roof", "cage", "guard", "frame"}

    def _clip_xy_region(
        self,
        verts: np.ndarray,
        *,
        keep_ratio_x: float = 0.7,
        keep_ratio_y: float = 0.7,
    ) -> np.ndarray:
        """
        只保留靠近中心的 XY 区域，用于估计“主平面”，避免被边缘突起/离群点干扰。
        """
        if len(verts) == 0:
            return verts

        bounds_min = verts.min(axis=0)
        bounds_max = verts.max(axis=0)
        center = (bounds_min + bounds_max) / 2.0
        ext = np.maximum(bounds_max - bounds_min, 1e-9)

        hx = ext[0] * keep_ratio_x * 0.5
        hy = ext[1] * keep_ratio_y * 0.5

        mask = (
            (verts[:, 0] >= center[0] - hx)
            & (verts[:, 0] <= center[0] + hx)
            & (verts[:, 1] >= center[1] - hy)
            & (verts[:, 1] <= center[1] + hy)
        )
        clipped = verts[mask]
        return clipped if len(clipped) > 0 else verts

    def _estimate_parent_mount_top_z(self, mesh: trimesh.Trimesh, category: str) -> tuple[float, Dict[str, Any]]:
        """
        估计父件“顶部主平面”高度，而不是直接用 bbox max z。
        目标：避免装甲车上的局部高突起把整个顶棚抬高。
        """
        verts = np.asarray(mesh.vertices, dtype=float)
        if len(verts) == 0:
            z = float(mesh.bounds[1][2])
            return z, {"method": "fallback_bbox_top", "sample_count": 0}

        clipped = self._clip_xy_region(verts, keep_ratio_x=0.72, keep_ratio_y=0.72)
        z_values = clipped[:, 2]

        z_min = float(z_values.min())
        z_max = float(z_values.max())
        z_span = max(z_max - z_min, 1e-9)

        # 先取顶部一段，再取较低分位，避免被最高尖点带偏
        top_band_threshold = z_max - 0.18 * z_span
        top_band = z_values[z_values >= top_band_threshold]
        if len(top_band) < 32:
            top_band = z_values

        mount_top_z = float(np.quantile(top_band, 0.20))

        diag = {
            "method": "central_top_band_quantile",
            "sample_count": int(len(clipped)),
            "top_band_count": int(len(top_band)),
            "z_min": z_min,
            "z_max": z_max,
            "z_span": z_span,
            "top_band_threshold": float(top_band_threshold),
            "mount_top_z": mount_top_z,
        }
        return mount_top_z, diag

    def _estimate_asset_mount_base_z(self, mesh: trimesh.Trimesh, category: str) -> tuple[float, Dict[str, Any]]:
        """
        估计新增件“安装基面”高度，而不是直接用 bbox min z。
        目标：避免个别向下突出的支撑杆/尖脚导致整体被抬高。
        """
        verts = np.asarray(mesh.vertices, dtype=float)
        if len(verts) == 0:
            z = float(mesh.bounds[0][2])
            return z, {"method": "fallback_bbox_bottom", "sample_count": 0}

        # 底部安装面通常更接近中心区域，因此也做一次中心裁剪
        clipped = self._clip_xy_region(verts, keep_ratio_x=0.88, keep_ratio_y=0.88)
        z_values = clipped[:, 2]

        z_min = float(z_values.min())
        z_max = float(z_values.max())
        z_span = max(z_max - z_min, 1e-9)

        # 先截取底部一段，再取偏高分位，过滤掉极少数低垂离群点
        bottom_band_threshold = z_min + 0.20 * z_span
        bottom_band = z_values[z_values <= bottom_band_threshold]
        if len(bottom_band) < 32:
            bottom_band = z_values

        mount_base_z = float(np.quantile(bottom_band, 0.80))

        diag = {
            "method": "central_bottom_band_quantile",
            "sample_count": int(len(clipped)),
            "bottom_band_count": int(len(bottom_band)),
            "z_min": z_min,
            "z_max": z_max,
            "z_span": z_span,
            "bottom_band_threshold": float(bottom_band_threshold),
            "mount_base_z": mount_base_z,
        }
        return mount_base_z, diag

    def _fit_visual_scale_factor(
        self,
        *,
        work_mesh: trimesh.Trimesh,
        parent_mesh: trimesh.Trimesh,
        imported_len: float,
        parent_len: float,
        category: str,
        fit_mode: str,
        coverage_ratio: float,
    ) -> tuple[float, Dict[str, Any]]:
        diagnostics: Dict[str, Any] = {
            "strategy": "none",
            "target_ratio_range": None,
            "target_len": None,
            "raw_scale_factor": None,
            "final_scale_factor": 1.0,
            "raw_scale_factor_xy_x": None,
            "raw_scale_factor_xy_y": None,
            "parent_xy": None,
            "asset_xy": None,
        }

        if imported_len <= 1e-6 or parent_len <= 1e-6:
            diagnostics["strategy"] = "skip_invalid_length"
            return 1.0, diagnostics

        category_lower = (category or "").strip().lower()

        if fit_mode == "cover_parent" and self._is_large_cover_part(category_lower):
            parent_x, parent_y = self._xy_extents(parent_mesh)
            asset_x, asset_y = self._xy_extents(work_mesh)

            diagnostics["parent_xy"] = [float(parent_x), float(parent_y)]
            diagnostics["asset_xy"] = [float(asset_x), float(asset_y)]

            if asset_x > 1e-6 and asset_y > 1e-6 and parent_x > 1e-6 and parent_y > 1e-6:
                target_x = parent_x * coverage_ratio
                target_y = parent_y * coverage_ratio

                raw_fx = target_x / asset_x
                raw_fy = target_y / asset_y

                raw_factor = min(raw_fx, raw_fy)
                final_factor = float(np.clip(raw_factor, 0.5, 5000.0))

                diagnostics["strategy"] = "cover_parent_xy"
                diagnostics["raw_scale_factor"] = float(raw_factor)
                diagnostics["raw_scale_factor_xy_x"] = float(raw_fx)
                diagnostics["raw_scale_factor_xy_y"] = float(raw_fy)
                diagnostics["final_scale_factor"] = final_factor
                diagnostics["target_len"] = float(parent_len * coverage_ratio)
                return final_factor, diagnostics

        if fit_mode == "cover_parent":
            target_len = parent_len * max(0.05, coverage_ratio)
            raw_factor = target_len / imported_len

            if self._is_large_cover_part(category_lower):
                final_factor = float(np.clip(raw_factor, 0.5, 5000.0))
            else:
                final_factor = float(np.clip(raw_factor, 0.5, 50.0))

            diagnostics["strategy"] = "cover_parent_length"
            diagnostics["target_len"] = float(target_len)
            diagnostics["raw_scale_factor"] = float(raw_factor)
            diagnostics["final_scale_factor"] = final_factor
            return final_factor, diagnostics

        min_ratio, max_ratio = self._default_visual_ratio_range(category_lower)
        target_ratio = min_ratio if fit_mode == "keep_original" else (min_ratio + max_ratio) / 2.0
        target_len = parent_len * target_ratio
        raw_factor = target_len / imported_len

        if fit_mode == "keep_original":
            final_factor = float(np.clip(raw_factor, 1.0, 20.0))
        else:
            final_factor = float(np.clip(raw_factor, 0.8, 30.0))

        diagnostics["strategy"] = fit_mode
        diagnostics["target_ratio_range"] = [float(min_ratio), float(max_ratio)]
        diagnostics["target_len"] = float(target_len)
        diagnostics["raw_scale_factor"] = float(raw_factor)
        diagnostics["final_scale_factor"] = final_factor
        return final_factor, diagnostics

    def _compute_bounded_stretch_target_len(
        self,
        *,
        current_len: float,
        parent_len: float,
        category: str,
        fit_mode: str,
        coverage_ratio: float,
    ) -> tuple[float, Dict[str, Any]]:
        diagnostics: Dict[str, Any] = {
            "strategy": "none",
            "target_len": None,
            "raw_scale_factor": None,
            "final_scale_factor": 1.0,
        }

        if current_len <= 1e-6 or parent_len <= 1e-6:
            diagnostics["strategy"] = "skip_invalid_length"
            return current_len, diagnostics

        category_lower = (category or "").strip().lower()

        if fit_mode == "keep_original":
            diagnostics["strategy"] = "keep_original_skip_stretch"
            diagnostics["target_len"] = float(current_len)
            diagnostics["raw_scale_factor"] = 1.0
            diagnostics["final_scale_factor"] = 1.0
            return current_len, diagnostics

        if fit_mode == "cover_parent":
            target_len = parent_len * max(0.05, coverage_ratio)
            raw_factor = target_len / current_len

            if self._is_large_cover_part(category_lower):
                final_factor = float(np.clip(raw_factor, 0.67, 8.0))
            else:
                final_factor = float(np.clip(raw_factor, 0.67, 3.0))

            diagnostics["strategy"] = "cover_parent"
            diagnostics["target_len"] = float(current_len * final_factor)
            diagnostics["raw_scale_factor"] = float(raw_factor)
            diagnostics["final_scale_factor"] = final_factor
            return float(current_len * final_factor), diagnostics

        min_ratio, max_ratio = self._default_visual_ratio_range(category_lower)
        desired_ratio = max_ratio
        target_len = parent_len * desired_ratio
        raw_factor = target_len / current_len
        final_factor = float(np.clip(raw_factor, 0.8, 2.5))

        diagnostics["strategy"] = "bounded_fit"
        diagnostics["target_len"] = float(current_len * final_factor)
        diagnostics["raw_scale_factor"] = float(raw_factor)
        diagnostics["final_scale_factor"] = final_factor
        return float(current_len * final_factor), diagnostics

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

        attach_axis = self._find_attach_axis(attach_to)
        attach_axis_xy = np.asarray([attach_axis[0], attach_axis[1], 0.0], dtype=float)
        if np.linalg.norm(attach_axis_xy) < 1e-9:
            attach_axis_xy = np.asarray([1.0, 0.0, 0.0], dtype=float)
        attach_axis_xy = self._normalize(attach_axis_xy)

        category = str(
            asset_metadata.get("category")
            or fit_policy.get("category")
            or asset_metadata.get("mount_region")
            or ""
        ).strip().lower()

        coverage_ratio = float(
            fit_policy.get("coverage_ratio", self._default_coverage_ratio(category))
        )
        allow_stretch = bool(
            fit_policy.get("allow_stretch", self._default_allow_stretch(category))
        )
        clearance_mm = self._find_clearance(attach_to, fit_policy)
        fit_mode = self._get_fit_mode(fit_policy)

        # 第一步：粗旋转
        axes, _ = self._principal_axes(work_mesh)
        thin_axis = axes[-1]

        rot1 = self._rotation_matrix_align_vectors(
            thin_axis,
            np.asarray([0.0, 0.0, 1.0], dtype=float),
            imported_center,
        )
        work_mesh.apply_transform(rot1)

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

        # 第二步：视觉量级归一化
        imported_len = self._extent_along_axis(work_mesh, attach_axis_xy)
        parent_len = self._extent_along_axis(parent_mesh, attach_axis_xy)

        visual_scale_factor, visual_scale_diag = self._fit_visual_scale_factor(
            work_mesh=work_mesh,
            parent_mesh=parent_mesh,
            imported_len=imported_len,
            parent_len=parent_len,
            category=category,
            fit_mode=fit_mode,
            coverage_ratio=coverage_ratio,
        )

        visual_scale_applied = 1.0
        if abs(visual_scale_factor - 1.0) > 1e-6:
            try:
                scale_anchor = self._mesh_bounds_center(work_mesh)
                scale_mat = self._uniform_scale_matrix_about_point(
                    scale_factor=visual_scale_factor,
                    anchor_point=scale_anchor,
                )
                work_mesh.apply_transform(scale_mat)
                visual_scale_applied = visual_scale_factor

                if visual_scale_factor > 10.0:
                    warnings.append(
                        f"large_uniform_scale_applied={visual_scale_factor:.3f}; "
                        "remote asset was likely much smaller than parent"
                    )
            except Exception as exc:
                warnings.append(f"visual scale normalization skipped: {exc}")

        # 第三步：有限轴向 stretch
        stretch_delta_mm = 0.0
        stretch_scale_factor_applied = 1.0
        stretch_diag: Dict[str, Any] = {
            "strategy": "disabled",
            "target_len": None,
            "raw_scale_factor": None,
            "final_scale_factor": 1.0,
        }

        if allow_stretch:
            try:
                current_len = self._extent_along_axis(work_mesh, attach_axis_xy)
                target_len, stretch_diag = self._compute_bounded_stretch_target_len(
                    current_len=current_len,
                    parent_len=parent_len,
                    category=category,
                    fit_mode=fit_mode,
                    coverage_ratio=coverage_ratio,
                )

                if current_len > 1e-6 and target_len > 1e-6:
                    stretch_scale_factor = target_len / current_len
                    stretch_scale_factor_applied = float(stretch_scale_factor)
                    stretch_delta_mm = float(target_len - current_len)

                    if abs(stretch_scale_factor - 1.0) > 1e-6:
                        stretch_anchor = self._mesh_bounds_center(work_mesh)
                        stretch_mat = self._stretch_matrix_about_point(
                            axis=attach_axis_xy,
                            scale_factor=stretch_scale_factor,
                            anchor_point=stretch_anchor,
                        )
                        work_mesh.apply_transform(stretch_mat)

                        if stretch_scale_factor > 2.0:
                            warnings.append(
                                f"large_axis_stretch_applied={stretch_scale_factor:.3f}"
                            )
            except Exception as exc:
                warnings.append(f"bounded stretch skipped: {exc}")
        else:
            stretch_diag["strategy"] = "allow_stretch_false"

        # 第四步：顶部挂载面对齐（第三轮核心改动）
        work_center = self._mesh_bounds_center(work_mesh)

        parent_mount_top_z, parent_mount_diag = self._estimate_parent_mount_top_z(
            parent_mesh,
            category=category,
        )
        asset_mount_base_z, asset_mount_diag = self._estimate_asset_mount_base_z(
            work_mesh,
            category=category,
        )

        # 对大覆盖件，clearance 不宜过于夸张；保留用户意图，但做一个温和限制，减少悬空观感
        effective_clearance_mm = float(clearance_mm)
        if self._is_large_cover_part(category):
            effective_clearance_mm = float(np.clip(clearance_mm, 0.0, 10.0))

        translate_vec = np.asarray(
            [
                float(parent_center[0] - work_center[0]),
                float(parent_center[1] - work_center[1]),
                float(parent_mount_top_z - asset_mount_base_z + effective_clearance_mm),
            ],
            dtype=float,
        )

        trans_mat = np.eye(4, dtype=float)
        trans_mat[:3, 3] = translate_vec
        work_mesh.apply_transform(trans_mat)

        final_extents = self._safe_extents(work_mesh)
        parent_extents = self._safe_extents(parent_mesh)

        fit_plan: Dict[str, Any] = {
            "attach_to": attach_to,
            "category": category,
            "fit_mode": fit_mode,
            "coverage_ratio": coverage_ratio,
            "allow_stretch": allow_stretch,
            "clearance_mm": clearance_mm,
            "effective_clearance_mm": effective_clearance_mm,
            "parent_extents": {
                "x": float(parent_extents[0]),
                "y": float(parent_extents[1]),
                "z": float(parent_extents[2]),
            },
            "final_asset_extents": {
                "x": float(final_extents[0]),
                "y": float(final_extents[1]),
                "z": float(final_extents[2]),
            },
            "visual_scale_normalization": visual_scale_diag,
            "visual_scale_applied": float(visual_scale_applied),
            "mount_alignment": {
                "parent_mount_top_z": float(parent_mount_top_z),
                "asset_mount_base_z": float(asset_mount_base_z),
                "parent_mount_diagnostics": parent_mount_diag,
                "asset_mount_diagnostics": asset_mount_diag,
            },
            "auto_translate": {
                "x": float(translate_vec[0]),
                "y": float(translate_vec[1]),
                "z": float(translate_vec[2]),
            },
            "auto_rotation": {
                "thin_axis_to_z": True,
                "long_axis_to_parent_primary_axis": True,
            },
            "bounded_stretch": stretch_diag,
            "auto_stretch_delta_mm": float(stretch_delta_mm),
            "axis_stretch_scale_factor_applied": float(stretch_scale_factor_applied),
        }

        # 第五步：轻量 overrides
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
                    if self._is_large_cover_part(category):
                        factor = float(np.clip(factor, 0.67, 3.0))
                    else:
                        factor = float(np.clip(factor, 0.67, 2.0))

                    extra_s = self._stretch_matrix_about_point(
                        axis=attach_axis_xy,
                        scale_factor=factor,
                        anchor_point=self._mesh_bounds_center(work_mesh),
                    )
                    work_mesh.apply_transform(extra_s)
                    overrides_applied["stretch"] = {
                        "delta_mm": delta_mm,
                        "clipped_scale_factor": factor,
                    }

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