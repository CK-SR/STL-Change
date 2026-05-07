from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import trimesh

from app.config import settings
from app.services.add_mount_planner import AddMountPlan, MountFrame
from app.services.add_pose_selection_service import PoseCandidate, PoseSelectionResult, VisionPoseSelectionService
from app.services.add_visual_scale_service import AddVisualScaleService, VisualScalePlan
from app.services.asset_mount_anchor_service import AssetMountAnchorService
from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.parent_mount_surface_service import (
    ParentMountSurface,
    ParentMountSurfacePlan,
    ParentMountSurfaceService,
)
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
    def __init__(
        self,
        *,
        anchor_service: Optional[GeometryAnchorService] = None,
        constraint_service: Optional[PartConstraintService] = None,
        surface_service: Optional[ParentMountSurfaceService] = None,
        asset_anchor_service: Optional[AssetMountAnchorService] = None,
        scale_service: Optional[AddVisualScaleService] = None,
        pose_selection_service: Optional[VisionPoseSelectionService] = None,
    ) -> None:
        self.anchor_service = anchor_service or GeometryAnchorService()
        self.constraint_service = constraint_service
        self.surface_service = surface_service or ParentMountSurfaceService(
            anchor_service=self.anchor_service,
            constraint_service=self.constraint_service,
        )
        self.asset_anchor_service = asset_anchor_service or AssetMountAnchorService()
        self.scale_service = scale_service or AddVisualScaleService()
        self.pose_selection_service = pose_selection_service or VisionPoseSelectionService()

    # =========================================================
    # 基础工具
    # =========================================================
    def _normalize(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _mesh_bounds_center(self, mesh: trimesh.Trimesh) -> np.ndarray:
        b = mesh.bounds
        return (b[0] + b[1]) / 2.0

    def _project_values(self, points: np.ndarray, axis: Iterable[float]) -> np.ndarray:
        axis_vec = self._normalize(axis)
        return np.dot(points, axis_vec)

    def _project_extent(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis_vec)
        return float(proj.max() - proj.min())

    def _projection_min(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis_vec)
        return float(proj.min())

    def _projection_center(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis_vec)
        return float((proj.min() + proj.max()) * 0.5)

    def _principal_axes(self, mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
        # Keep imported-asset axis inference consistent with the constraint builder,
        # which derives primary axes from trimesh.bounding_box_oriented when available.
        try:
            obb = mesh.bounding_box_oriented
            axes = np.asarray(obb.primitive.transform[:3, :3], dtype=float).T
            lengths = np.asarray(obb.primitive.extents, dtype=float)
            valid_axes = axes.shape == (3, 3) and np.all(np.isfinite(axes))
            valid_lengths = lengths.shape == (3,) and np.all(np.isfinite(lengths))
            if valid_axes and valid_lengths:
                return axes, lengths
        except Exception:
            pass

        extents = np.asarray(mesh.extents, dtype=float)
        return np.eye(3, dtype=float), extents

    def _rotation_matrix_align_vectors(self, src: np.ndarray, dst: np.ndarray, point: np.ndarray) -> np.ndarray:
        src = self._normalize(src)
        dst = self._normalize(dst)

        dot = float(np.clip(np.dot(src, dst), -1.0, 1.0))
        if abs(dot - 1.0) < 1e-8:
            return np.eye(4, dtype=float)

        if abs(dot + 1.0) < 1e-8:
            helper = np.asarray([1.0, 0.0, 0.0], dtype=float)
            if abs(np.dot(helper, src)) > 0.9:
                helper = np.asarray([0.0, 1.0, 0.0], dtype=float)
            axis = self._normalize(np.cross(src, helper))
            return trimesh.transformations.rotation_matrix(math.pi, axis, point)

        axis = self._normalize(np.cross(src, dst))
        angle = math.acos(dot)
        return trimesh.transformations.rotation_matrix(angle, axis, point)

    def _uniform_scale_matrix_about_point(self, *, scale_factor: float, anchor_point: np.ndarray) -> np.ndarray:
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

    def _stretch_matrix_about_point(self, *, axis: np.ndarray, scale_factor: float, anchor_point: np.ndarray) -> np.ndarray:
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

    # =========================================================
    # 请求解析
    # =========================================================
    def _resolve_mount_request(
        self,
        *,
        asset_metadata: Dict[str, Any],
        fit_policy: Dict[str, Any],
        mount_request: Dict[str, Any],
        visual_fit: Dict[str, Any],
    ) -> Dict[str, Any]:
        mount_region = (
            mount_request.get("mount_region")
            or asset_metadata.get("mount_region")
            or fit_policy.get("mount_region")
            or ""
        )
        placement_scope = mount_request.get("placement_scope", "")
        preferred_strategy = mount_request.get("preferred_strategy", "")
        category = str(
            asset_metadata.get("category")
            or fit_policy.get("category")
            or mount_region
            or ""
        ).strip().lower()
        return {
            "mount_region": str(mount_region).strip(),
            "placement_scope": str(placement_scope).strip(),
            "preferred_strategy": str(preferred_strategy).strip(),
            "category": category,
            "target_ratio": float(
                visual_fit.get(
                    "target_ratio",
                    fit_policy.get("coverage_ratio", 0.92),
                )
            ),
            "preserve_aspect_ratio": bool(
                visual_fit.get(
                    "preserve_aspect_ratio",
                    settings.add_default_preserve_aspect_ratio,
                )
            ),
            "allow_axis_stretch": bool(
                visual_fit.get(
                    "allow_axis_stretch",
                    fit_policy.get(
                        "allow_stretch",
                        settings.add_default_allow_axis_stretch,
                    ),
                )
            ),
            "allow_unlimited_upscale": bool(
                visual_fit.get(
                    "allow_unlimited_upscale",
                    settings.add_default_allow_unlimited_upscale,
                )
            ),
            "clearance_mm": float(fit_policy.get("clearance_mm", 0.0) or 0.0),
        }

    # =========================================================
    # P0：选材兼容性门禁
    # =========================================================
    def _category_family(self, text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return ""
        if any(k in t for k in ["roof", "top", "cage", "frame", "armor_cage"]):
            return "top_cover"
        if any(k in t for k in ["side", "panel", "guard", "net", "mesh"]):
            return "side_panel"
        if any(k in t for k in ["perimeter", "wrap", "dread", "cable", "rope", "chain", "guard_net"]):
            return "perimeter_wrap"
        return ""

    def _mount_region_family(self, text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return ""
        if t in {"turret_top", "top_hull", "top", "roof"}:
            return "top_cover"
        if t in {"hull_side", "side", "left_side", "right_side", "turret_side"}:
            return "side_panel"
        if t in {"turret_perimeter", "perimeter", "full_perimeter", "wrap", "rear", "front"}:
            return "perimeter_wrap"
        return ""

    def _validate_asset_choice(
        self,
        *,
        resolved_request: Dict[str, Any],
        asset_metadata: Dict[str, Any],
        mount_strategy: str,
    ) -> Dict[str, Any]:
        asset_category = str(asset_metadata.get("category", "")).strip()
        asset_mount_region = str(asset_metadata.get("mount_region", "")).strip()

        category_family = self._category_family(asset_category)
        region_family = self._mount_region_family(asset_mount_region)

        compatible = True
        reasons: list[str] = []

        if mount_strategy == "top_cover":
            if category_family not in {"", "top_cover"} and region_family not in {"", "top_cover"}:
                compatible = False
                reasons.append("selected asset is not compatible with top_cover")
        elif mount_strategy == "side_panel":
            if category_family not in {"", "side_panel", "perimeter_wrap"} and region_family not in {"", "side_panel"}:
                compatible = False
                reasons.append("selected asset is not compatible with side_panel")
        elif mount_strategy == "perimeter_wrap":
            if category_family in {"top_cover"} or region_family in {"top_cover"}:
                compatible = False
                reasons.append("selected asset looks like roof/top_cover, not perimeter_wrap")

        return {
            "compatible": compatible,
            "mount_strategy": mount_strategy,
            "asset_category": asset_category,
            "asset_mount_region": asset_mount_region,
            "category_family": category_family,
            "region_family": region_family,
            "reasons": reasons,
        }

    # =========================================================
    # 资产粗对齐 / 细对齐
    # =========================================================
    def _coarse_orient_source_to_frame(self, mesh: trimesh.Trimesh, frame: MountFrame) -> Dict[str, Any]:
        center = self._mesh_bounds_center(mesh)
        axes, lengths = self._principal_axes(mesh)
        thin_axis = np.asarray(axes[int(np.argmin(lengths))], dtype=float)
        normal = np.asarray(frame.normal, dtype=float)

        rot1 = self._rotation_matrix_align_vectors(thin_axis, normal, center)
        mesh.apply_transform(rot1)

        center2 = self._mesh_bounds_center(mesh)
        axes2, lengths2 = self._principal_axes(mesh)
        longest_axis = np.asarray(axes2[int(np.argmax(lengths2))], dtype=float)
        longest_plane = longest_axis - np.dot(longest_axis, normal) * normal
        if np.linalg.norm(longest_plane) < 1e-9:
            longest_plane = np.asarray(frame.tangent, dtype=float)

        tangent = np.asarray(frame.tangent, dtype=float)
        rot2 = self._rotation_matrix_align_vectors(longest_plane, tangent, center2)
        mesh.apply_transform(rot2)

        return {
            "coarse_center_before": [float(x) for x in center.tolist()],
            "coarse_center_after": [float(x) for x in self._mesh_bounds_center(mesh).tolist()],
        }

    def _refine_anchor_inplane_axis(
        self,
        mesh: trimesh.Trimesh,
        *,
        anchor_info: Dict[str, Any],
        frame: MountFrame,
    ) -> Dict[str, Any]:
        current_axis = np.asarray(anchor_info["inplane_axis"], dtype=float)
        target_axis = np.asarray(frame.tangent, dtype=float)
        center = np.asarray(anchor_info["alignment_center"], dtype=float)

        dot = float(np.clip(np.dot(self._normalize(current_axis), self._normalize(target_axis)), -1.0, 1.0))
        angle_deg = float(math.degrees(math.acos(dot)))

        if angle_deg < 0.3:
            return {
                "rotation_applied": False,
                "rotation_deg": angle_deg,
                "message": "inplane axis already aligned",
            }

        rot = self._rotation_matrix_align_vectors(current_axis, target_axis, center)
        mesh.apply_transform(rot)
        return {
            "rotation_applied": True,
            "rotation_deg": angle_deg,
            "message": "inplane anchor axis aligned to frame tangent",
        }

    # =========================================================
    # 缩放 / 放置
    # =========================================================
    def _apply_scale_plan(
        self,
        mesh: trimesh.Trimesh,
        scale_plan: VisualScalePlan,
        warnings: List[str],
        *,
        anchor_point: np.ndarray,
    ) -> Dict[str, Any]:
        applied: Dict[str, Any] = {
            "uniform_scale_applied": 1.0,
            "axis_stretch_applied": None,
        }

        if abs(scale_plan.uniform_scale_factor - 1.0) > 1e-9:
            mat = self._uniform_scale_matrix_about_point(
                scale_factor=float(scale_plan.uniform_scale_factor),
                anchor_point=anchor_point,
            )
            mesh.apply_transform(mat)
            applied["uniform_scale_applied"] = float(scale_plan.uniform_scale_factor)
            if scale_plan.uniform_scale_factor > 10.0:
                warnings.append(
                    f"large_uniform_scale_applied={scale_plan.uniform_scale_factor:.3f}; remote asset was likely much smaller than parent"
                )

        stretch = scale_plan.axis_stretch or {}
        factor = float(stretch.get("scale_factor", 1.0) or 1.0)
        axis_vec = stretch.get("axis_vector")
        if axis_vec is not None and abs(factor - 1.0) > 1e-9:
            mat = self._stretch_matrix_about_point(
                axis=np.asarray(axis_vec, dtype=float),
                scale_factor=factor,
                anchor_point=anchor_point,
            )
            mesh.apply_transform(mat)
            applied["axis_stretch_applied"] = {
                "axis_vector": [float(x) for x in axis_vec],
                "scale_factor": factor,
                "reason": stretch.get("reason", ""),
            }
            if factor > 2.0:
                warnings.append(f"large_axis_stretch_applied={factor:.3f}")

        return applied

    def _place_mesh_on_surface(
        self,
        mesh: trimesh.Trimesh,
        *,
        frame: MountFrame,
        anchor_info: Dict[str, Any],
        clearance_mm: float,
    ) -> Dict[str, Any]:
        normal = np.asarray(frame.normal, dtype=float)
        tangent = np.asarray(frame.tangent, dtype=float)
        bitangent = np.asarray(frame.bitangent, dtype=float)
        origin = np.asarray(frame.origin, dtype=float)

        current_support_level = float(anchor_info["support_level_mean"])
        current_t_center = float(anchor_info["placement_t_center"])
        current_b_center = float(anchor_info["placement_b_center"])

        target_support_level = float(np.dot(origin, normal) + clearance_mm)
        target_t_center = float(np.dot(origin, tangent))
        target_b_center = float(np.dot(origin, bitangent))

        delta = (
            (target_support_level - current_support_level) * normal
            + (target_t_center - current_t_center) * tangent
            + (target_b_center - current_b_center) * bitangent
        )

        mat = np.eye(4, dtype=float)
        mat[:3, 3] = delta
        mesh.apply_transform(mat)

        return {
            "translate": {
                "x": float(delta[0]),
                "y": float(delta[1]),
                "z": float(delta[2]),
            },
            "target_support_level": target_support_level,
            "frame_origin": [float(x) for x in origin.tolist()],
            "current_t_center_before_translate": current_t_center,
            "current_b_center_before_translate": current_b_center,
            "target_t_center": target_t_center,
            "target_b_center": target_b_center,
        }

    def _apply_post_overrides(
        self,
        mesh: trimesh.Trimesh,
        *,
        post_transform_overrides: Dict[str, Any],
        primary_axis: Iterable[float],
    ) -> Dict[str, Any]:
        overrides_applied: Dict[str, Any] = {}

        translate_override = post_transform_overrides.get("translate")
        if isinstance(translate_override, dict):
            dx = float(translate_override.get("x", 0.0))
            dy = float(translate_override.get("y", 0.0))
            dz = float(translate_override.get("z", 0.0))
            mat = np.eye(4, dtype=float)
            mat[:3, 3] = np.asarray([dx, dy, dz], dtype=float)
            mesh.apply_transform(mat)
            overrides_applied["translate"] = {"x": dx, "y": dy, "z": dz}

        rotate_override = post_transform_overrides.get("rotate")
        if isinstance(rotate_override, dict):
            degrees = float(rotate_override.get("degrees", 0.0))
            axis_name = str(rotate_override.get("axis", "z")).strip().lower()
            axis_map = {
                "x": np.asarray([1.0, 0.0, 0.0], dtype=float),
                "y": np.asarray([0.0, 1.0, 0.0], dtype=float),
                "z": np.asarray([0.0, 0.0, 1.0], dtype=float),
            }
            axis_vec = axis_map.get(axis_name, np.asarray([0.0, 0.0, 1.0], dtype=float))
            rot = trimesh.transformations.rotation_matrix(
                angle=math.radians(degrees),
                direction=axis_vec,
                point=self._mesh_bounds_center(mesh),
            )
            mesh.apply_transform(rot)
            overrides_applied["rotate"] = {"axis": axis_name, "degrees": degrees}

        stretch_override = post_transform_overrides.get("stretch")
        if isinstance(stretch_override, dict):
            delta_mm = float(stretch_override.get("delta_mm", 0.0))
            if abs(delta_mm) > 1e-9:
                axis = self._normalize(list(primary_axis))
                current_len = self._project_extent(mesh, axis)
                target_len = current_len + delta_mm
                if current_len > 1e-9 and target_len > 1e-9:
                    factor = float(target_len / current_len)
                    mat = self._stretch_matrix_about_point(
                        axis=axis,
                        scale_factor=factor,
                        anchor_point=self._mesh_bounds_center(mesh),
                    )
                    mesh.apply_transform(mat)
                    overrides_applied["stretch"] = {
                        "delta_mm": delta_mm,
                        "scale_factor": factor,
                    }

        return overrides_applied

    def _merge_meshes(self, meshes: List[trimesh.Trimesh]) -> trimesh.Trimesh:
        if len(meshes) == 1:
            return meshes[0]
        return trimesh.util.concatenate(tuple(meshes))

    # =========================================================
    # 支撑点 / 附着 / 质量检查
    # =========================================================
    def _count_support_regions(
        self,
        points: np.ndarray,
        tangent: Iterable[float],
        bitangent: Iterable[float],
        grid_size: int = 4,
    ) -> int:
        if points.size == 0 or len(points) < 3:
            return 0

        t = self._project_values(points, tangent)
        b = self._project_values(points, bitangent)

        t_min, t_max = float(t.min()), float(t.max())
        b_min, b_max = float(b.min()), float(b.max())

        if (t_max - t_min) < 1e-6 and (b_max - b_min) < 1e-6:
            return 1

        occupied = set()
        for tv, bv in zip(t.tolist(), b.tolist()):
            ti = 0 if (t_max - t_min) < 1e-6 else min(
                grid_size - 1, max(0, int(((tv - t_min) / max(t_max - t_min, 1e-9)) * grid_size))
            )
            bi = 0 if (b_max - b_min) < 1e-6 else min(
                grid_size - 1, max(0, int(((bv - b_min) / max(b_max - b_min, 1e-9)) * grid_size))
            )
            occupied.add((ti, bi))

        return len(occupied)

    def _fit_plane_normal(
        self,
        points: np.ndarray,
        *,
        preferred_normal: Iterable[float],
    ) -> Dict[str, Any]:
        preferred = self._normalize(preferred_normal)

        if points.size == 0 or len(points) < 3:
            return {
                "success": False,
                "plane_normal": preferred,
                "centroid": np.zeros(3, dtype=float),
                "spread_mm": 0.0,
                "message": "not enough support points for plane fitting",
            }

        centroid = points.mean(axis=0)
        centered = points - centroid
        cov = np.dot(centered.T, centered) / max(len(points) - 1, 1)
        eigvals, eigvecs = np.linalg.eigh(cov)
        plane_normal = eigvecs[:, int(np.argmin(eigvals))]
        plane_normal = self._normalize(plane_normal)

        if float(np.dot(plane_normal, preferred)) < 0:
            plane_normal = -plane_normal

        spreads = np.abs(np.dot(centered, plane_normal))
        spread_mm = float(np.max(spreads)) if len(spreads) else 0.0

        return {
            "success": True,
            "plane_normal": plane_normal,
            "centroid": centroid,
            "spread_mm": spread_mm,
            "message": "support plane fitted",
        }

    def _resolve_settle_gap_mm(
        self,
        *,
        mount_strategy: str,
        requested_clearance_mm: float,
    ) -> float:
        clearance = float(requested_clearance_mm or 0.0)
        if mount_strategy in {"top_cover", "side_panel", "rear_frame"}:
            return min(clearance, 2.0)
        if mount_strategy == "perimeter_wrap":
            return min(clearance, 5.0)
        return clearance

    def _check_support_inside_footprint(
        self,
        points: np.ndarray,
        *,
        frame: MountFrame,
        footprint_bounds: Dict[str, float],
        tolerance_mm: float = 5.0,
    ) -> Dict[str, Any]:
        if points.size == 0:
            return {
                "contact_point_count": 0,
                "outside_count": 0,
                "outside_ratio": 0.0,
            }

        proj_t = self._project_values(points, frame.tangent)
        proj_b = self._project_values(points, frame.bitangent)

        inside = (
            (proj_t >= footprint_bounds["t_min"] - tolerance_mm)
            & (proj_t <= footprint_bounds["t_max"] + tolerance_mm)
            & (proj_b >= footprint_bounds["b_min"] - tolerance_mm)
            & (proj_b <= footprint_bounds["b_max"] + tolerance_mm)
        )
        outside_count = int(np.count_nonzero(~inside))
        total = int(len(points))
        outside_ratio = float(outside_count / max(total, 1))
        return {
            "contact_point_count": total,
            "outside_count": outside_count,
            "outside_ratio": outside_ratio,
        }

    def _settle_mesh_supports_to_surface(
        self,
        mesh: trimesh.Trimesh,
        *,
        frame: MountFrame,
        surface: ParentMountSurface,
        mount_strategy: str,
        requested_clearance_mm: float,
        warnings: List[str],
    ) -> Dict[str, Any]:
        normal = np.asarray(frame.normal, dtype=float)
        target_origin = np.asarray(frame.origin, dtype=float)

        support_info_before = self.asset_anchor_service.analyze_oriented_asset(
            mesh,
            frame=frame,
            mount_strategy=mount_strategy,
        )
        support_points_before = np.asarray(support_info_before["support_points"], dtype=float)

        settle_gap_mm = self._resolve_settle_gap_mm(
            mount_strategy=mount_strategy,
            requested_clearance_mm=requested_clearance_mm,
        )
        if settle_gap_mm < float(requested_clearance_mm or 0.0):
            warnings.append(
                f"settle_gap_reduced_from_clearance={float(requested_clearance_mm):.3f}->{settle_gap_mm:.3f}"
            )

        plane_fit_before = self._fit_plane_normal(
            support_points_before,
            preferred_normal=normal,
        )

        rotation_applied = False
        rotation_deg = 0.0
        support_center = plane_fit_before["centroid"]

        if plane_fit_before["success"]:
            plane_normal = plane_fit_before["plane_normal"]
            dot = float(np.clip(np.dot(plane_normal, normal), -1.0, 1.0))
            rotation_deg = float(math.degrees(math.acos(dot)))
            if rotation_deg > 0.5:
                rot = self._rotation_matrix_align_vectors(plane_normal, normal, support_center)
                mesh.apply_transform(rot)
                rotation_applied = True

        support_info_after_align = self.asset_anchor_service.analyze_oriented_asset(
            mesh,
            frame=frame,
            mount_strategy=mount_strategy,
        )
        support_points_after_align = np.asarray(support_info_after_align["support_points"], dtype=float)

        if support_points_after_align.size == 0:
            warnings.append("support_settle_failed=no_support_points_after_align")
            return {
                "settle_gap_mm": settle_gap_mm,
                "rotation_applied": rotation_applied,
                "rotation_deg": rotation_deg,
                "support_regions_before": 0,
                "support_regions_after_align": 0,
                "contact_regions_final": 0,
                "hover_gap_mm": None,
                "support_plane_spread_mm": None,
                "outside_footprint_ratio": 0.0,
                "message": "support settle skipped because no support points were found",
            }

        proj_support = self._project_values(support_points_after_align, normal)
        current_support_level = float(np.mean(proj_support))
        target_support_level = float(np.dot(target_origin, normal) + settle_gap_mm)

        delta = (target_support_level - current_support_level) * normal
        mat = np.eye(4, dtype=float)
        mat[:3, 3] = delta
        mesh.apply_transform(mat)

        final_support_info = self.asset_anchor_service.analyze_oriented_asset(
            mesh,
            frame=frame,
            mount_strategy=mount_strategy,
        )
        final_support_points = np.asarray(final_support_info["support_points"], dtype=float)
        final_proj = self._project_values(final_support_points, normal) if final_support_points.size else np.asarray([], dtype=float)

        if len(final_proj) > 0:
            hover_gap_mm = float(max(0.0, float(final_proj.min()) - target_support_level))
            support_plane_spread_mm = float(final_proj.max() - final_proj.min())
            near_contact_mask = final_proj <= (target_support_level + 3.0)
            near_contact_pts = final_support_points[near_contact_mask] if np.any(near_contact_mask) else np.zeros((0, 3), dtype=float)
            contact_regions = self._count_support_regions(
                near_contact_pts,
                frame.tangent,
                frame.bitangent,
            )
            footprint_check = self._check_support_inside_footprint(
                near_contact_pts,
                frame=frame,
                footprint_bounds=surface.footprint_bounds,
                tolerance_mm=5.0,
            )
        else:
            hover_gap_mm = None
            support_plane_spread_mm = None
            contact_regions = 0
            footprint_check = {
                "contact_point_count": 0,
                "outside_count": 0,
                "outside_ratio": 0.0,
            }

        outside_ratio = float(footprint_check["outside_ratio"])

        if contact_regions < 2:
            warnings.append(f"support_contact_regions_low={contact_regions}")
        if hover_gap_mm is not None and hover_gap_mm > 5.0:
            warnings.append(f"support_hover_gap_large={hover_gap_mm:.3f}mm")
        if support_plane_spread_mm is not None and support_plane_spread_mm > 8.0:
            warnings.append(f"support_plane_spread_large={support_plane_spread_mm:.3f}mm")
        if outside_ratio > 0.20:
            warnings.append(f"support_outside_footprint_ratio_high={outside_ratio:.3f}")

        return {
            "settle_gap_mm": settle_gap_mm,
            "rotation_applied": rotation_applied,
            "rotation_deg": rotation_deg,
            "support_regions_before": self._count_support_regions(
                support_points_before,
                frame.tangent,
                frame.bitangent,
            ),
            "support_regions_after_align": self._count_support_regions(
                support_points_after_align,
                frame.tangent,
                frame.bitangent,
            ),
            "contact_regions_final": int(contact_regions),
            "hover_gap_mm": hover_gap_mm,
            "support_plane_spread_mm": support_plane_spread_mm,
            "outside_footprint_ratio": outside_ratio,
            "target_support_level": target_support_level,
            "current_support_level_before_translate": current_support_level,
            "translate_after_settle": {
                "x": float(delta[0]),
                "y": float(delta[1]),
                "z": float(delta[2]),
            },
            "message": "support plane aligned and settled toward mount surface",
        }

    def _validate_surface_fit(
        self,
        *,
        mount_strategy: str,
        support_settle: Dict[str, Any],
    ) -> Dict[str, Any]:
        errors: List[str] = []

        if mount_strategy == "top_cover":
            if int(support_settle.get("contact_regions_final", 0)) < 2:
                errors.append("top_cover has insufficient support contact regions")
            if float(support_settle.get("outside_footprint_ratio", 0.0)) > 0.35:
                errors.append("top_cover support points fall outside parent footprint too much")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    # =========================================================
    # 主流程
    # =========================================================
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
        mount_request: Dict[str, Any] | None = None,
        visual_fit: Dict[str, Any] | None = None,
    ) -> AddFitResult:
        fit_policy = fit_policy or {}
        post_transform_overrides = post_transform_overrides or {}
        asset_metadata = asset_metadata or {}
        mount_request = mount_request or {}
        visual_fit = visual_fit or {}
        warnings: List[str] = []

        try:
            imported_mesh = self.anchor_service.load_mesh(imported_stl_path)
            parent_mesh = self.anchor_service.load_mesh(attach_to_path)  # 校验并复用父部件网格
        except Exception as exc:
            return AddFitResult(False, "", {}, f"load mesh failed: {exc}", warnings)

        resolved = self._resolve_mount_request(
            asset_metadata=asset_metadata,
            fit_policy=fit_policy,
            mount_request=mount_request,
            visual_fit=visual_fit,
        )

        surface_plan = self.surface_service.plan_mount_surfaces(
            attach_to=attach_to,
            attach_to_path=attach_to_path,
            mount_region=resolved["mount_region"],
            placement_scope=resolved["placement_scope"],
            preferred_strategy=resolved["preferred_strategy"],
            category=resolved["category"],
        )
        if surface_plan.mount_strategy != "top_cover":
            return AddFitResult(
                success=False,
                output_path="",
                fit_plan={
                    "attach_to": attach_to,
                    "resolved_request": resolved,
                    "surface_plan": surface_plan.to_dict(),
                    "supported_mount_strategies": ["top_cover"],
                },
                message=(
                    f"add skipped: unsupported mount strategy {surface_plan.mount_strategy}; "
                    "only top_cover is enabled"
                ),
                warnings=warnings,
            )

        asset_match = self._validate_asset_choice(
            resolved_request=resolved,
            asset_metadata=asset_metadata,
            mount_strategy=surface_plan.mount_strategy,
        )
        if not asset_match["compatible"]:
            return AddFitResult(
                success=False,
                output_path="",
                fit_plan={
                    "attach_to": attach_to,
                    "resolved_request": resolved,
                    "surface_plan": surface_plan.to_dict(),
                    "asset_metadata": asset_metadata,
                    "asset_match_validation": asset_match,
                },
                message=f"selected asset is incompatible with mount strategy: {asset_match['reasons']}",
                warnings=warnings,
            )

        fitted_meshes: List[trimesh.Trimesh] = []
        surface_reports: List[Dict[str, Any]] = []

        for surface in surface_plan.surfaces:
            frame = surface.to_mount_frame()
            work_mesh = imported_mesh.copy()

            coarse_orientation = self._coarse_orient_source_to_frame(work_mesh, frame)

            anchor_before_refine = self.asset_anchor_service.analyze_oriented_asset(
                work_mesh,
                frame=frame,
                mount_strategy=surface_plan.mount_strategy,
            )
            refine_report = self._refine_anchor_inplane_axis(
                work_mesh,
                anchor_info=anchor_before_refine,
                frame=frame,
            )

            anchor_after_refine = self.asset_anchor_service.analyze_oriented_asset(
                work_mesh,
                frame=frame,
                mount_strategy=surface_plan.mount_strategy,
            )

            single_frame_plan = AddMountPlan(
                mount_strategy=surface_plan.mount_strategy,
                placement_scope=surface_plan.placement_scope,
                attach_to=surface_plan.attach_to,
                frames=[frame],
                preserve_aspect_ratio=resolved["preserve_aspect_ratio"],
                allow_axis_stretch=resolved["allow_axis_stretch"],
                diagnostics=surface_plan.diagnostics,
            )

            max_pose_candidates = (
                settings.add_vision_pose_max_candidates
                if settings.add_vision_pose_selection_enabled
                else 1
            )
            pose_seed_specs = self.pose_selection_service.build_candidate_seed_transforms(
                normal=frame.normal,
                tangent=frame.tangent,
                bitangent=frame.bitangent,
                origin=anchor_after_refine["alignment_center"],
                max_candidates=max_pose_candidates,
            )

            valid_pose_candidates: List[PoseCandidate] = []
            invalid_pose_reports: List[Dict[str, Any]] = []

            for seed_spec in pose_seed_specs:
                candidate_mesh = work_mesh.copy()
                candidate_mesh.apply_transform(seed_spec["transform"])

                candidate_anchor_before_scale = self.asset_anchor_service.analyze_oriented_asset(
                    candidate_mesh,
                    frame=frame,
                    mount_strategy=surface_plan.mount_strategy,
                )

                scale_plan = self.scale_service.compute_visual_scale_plan(
                    oriented_mesh=candidate_mesh,
                    parent_mesh=parent_mesh,
                    mount_plan=single_frame_plan,
                    target_ratio=resolved["target_ratio"],
                    preserve_aspect_ratio=resolved["preserve_aspect_ratio"],
                    allow_axis_stretch=resolved["allow_axis_stretch"],
                    allow_unlimited_upscale=resolved["allow_unlimited_upscale"],
                )

                scale_applied = self._apply_scale_plan(
                    candidate_mesh,
                    scale_plan,
                    warnings,
                    anchor_point=np.asarray(candidate_anchor_before_scale["alignment_center"], dtype=float),
                )

                anchor_after_scale = self.asset_anchor_service.analyze_oriented_asset(
                    candidate_mesh,
                    frame=frame,
                    mount_strategy=surface_plan.mount_strategy,
                )

                placement = self._place_mesh_on_surface(
                    candidate_mesh,
                    frame=frame,
                    anchor_info=anchor_after_scale,
                    clearance_mm=resolved["clearance_mm"],
                )

                support_settle = self._settle_mesh_supports_to_surface(
                    candidate_mesh,
                    frame=frame,
                    surface=surface,
                    mount_strategy=surface_plan.mount_strategy,
                    requested_clearance_mm=resolved["clearance_mm"],
                    warnings=warnings,
                )

                surface_validation = self._validate_surface_fit(
                    mount_strategy=surface_plan.mount_strategy,
                    support_settle=support_settle,
                )
                candidate_report = {
                    "candidate_id": seed_spec["candidate_id"],
                    "description": seed_spec["description"],
                    "pose_seed_transform": seed_spec["transform"].tolist(),
                    "pose_seed_rotations": seed_spec.get("rotations", []),
                    "anchor_before_scale": candidate_anchor_before_scale["report"],
                    "scale_plan": scale_plan.to_dict(),
                    "scale_applied": scale_applied,
                    "anchor_after_scale": anchor_after_scale["report"],
                    "placement": placement,
                    "support_settle": support_settle,
                    "surface_validation": surface_validation,
                    "final_extents": {
                        "x": float(candidate_mesh.extents[0]),
                        "y": float(candidate_mesh.extents[1]),
                        "z": float(candidate_mesh.extents[2]),
                    },
                }

                if surface_validation["valid"]:
                    valid_pose_candidates.append(
                        PoseCandidate(
                            candidate_id=seed_spec["candidate_id"],
                            mesh=candidate_mesh,
                            transform=seed_spec["transform"],
                            description=seed_spec["description"],
                            geometry_report=candidate_report,
                        )
                    )
                else:
                    invalid_pose_reports.append(candidate_report)

            if not valid_pose_candidates:
                return AddFitResult(
                    success=False,
                    output_path="",
                    fit_plan={
                        "attach_to": attach_to,
                        "resolved_request": resolved,
                        "surface_plan": surface_plan.to_dict(),
                        "surface_reports": surface_reports,
                        "failed_surface": surface.to_dict(),
                        "invalid_pose_candidates": invalid_pose_reports,
                        "asset_metadata": asset_metadata,
                        "asset_match_validation": asset_match,
                    },
                    message="surface fit validation failed for all pose candidates",
                    warnings=warnings,
                )

            try:
                pose_selection = self.pose_selection_service.select_best_candidate(
                    parent_mesh=parent_mesh,
                    candidates=valid_pose_candidates,
                    mount_strategy=surface_plan.mount_strategy,
                    attach_to=attach_to,
                    asset_metadata=asset_metadata,
                    run_id=f"{Path(output_path).stem}_{surface.region_name}_{len(surface_reports)}",
                )
                warnings.extend(pose_selection.warnings)
            except Exception as exc:
                warnings.append(f"vision_pose_selection_failed={exc}; fallback_to_first_valid_candidate")
                pose_selection = PoseSelectionResult(
                    enabled=False,
                    selected_candidate_id=valid_pose_candidates[0].candidate_id,
                    selected_index=0,
                    candidates=[candidate.to_dict() for candidate in valid_pose_candidates],
                    scores=[],
                    render_paths=[],
                    message="vision pose selection failed; using first valid candidate",
                    warnings=[str(exc)],
                )

            selected_candidate = valid_pose_candidates[int(pose_selection.selected_index)]
            fitted_meshes.append(selected_candidate.mesh)
            selected_report = selected_candidate.geometry_report
            surface_reports.append(
                {
                    "surface": surface.to_dict(),
                    "coarse_orientation": coarse_orientation,
                    "anchor_before_refine": anchor_before_refine["report"],
                    "refine_report": refine_report,
                    "anchor_after_refine": anchor_after_refine["report"],
                    "pose_selection": pose_selection.to_dict(),
                    "selected_pose_candidate": selected_report,
                    "invalid_pose_candidates": invalid_pose_reports,
                    "final_extents": selected_report["final_extents"],
                }
            )

        combined = self._merge_meshes(fitted_meshes)

        primary_axis = np.asarray(surface_plan.surfaces[0].tangent, dtype=float)
        overrides_applied = self._apply_post_overrides(
            combined,
            post_transform_overrides=post_transform_overrides,
            primary_axis=primary_axis,
        )

        # P0：多 surface（尤其 perimeter_wrap）不再对 merge 后整体再次按单 frame 落座
        if len(fitted_meshes) == 1:
            combined_support_settle = self._settle_mesh_supports_to_surface(
                combined,
                frame=surface_plan.surfaces[0].to_mount_frame(),
                surface=surface_plan.surfaces[0],
                mount_strategy=surface_plan.mount_strategy,
                requested_clearance_mm=resolved["clearance_mm"],
                warnings=warnings,
            )
        else:
            combined_support_settle = {
                "skipped": True,
                "reason": "multi_surface_asset_skip_combined_support_settle",
            }

        try:
            saved = self.anchor_service.save_mesh(combined, output_path)
        except Exception as exc:
            return AddFitResult(False, "", {}, f"export fitted asset failed: {exc}", warnings)

        fit_plan: Dict[str, Any] = {
            "attach_to": attach_to,
            "resolved_request": resolved,
            "surface_plan": surface_plan.to_dict(),
            "surface_reports": surface_reports,
            "asset_metadata": asset_metadata,
            "asset_match_validation": asset_match,
            "overrides_applied": overrides_applied,
            "combined_support_settle": combined_support_settle,
            "final_asset_extents": {
                "x": float(combined.extents[0]),
                "y": float(combined.extents[1]),
                "z": float(combined.extents[2]),
            },
            "instance_count": len(fitted_meshes),
        }

        return AddFitResult(
            success=True,
            output_path=saved,
            fit_plan=fit_plan,
            message="add success via structured mount surface + asset anchor + local fit",
            warnings=warnings,
        )