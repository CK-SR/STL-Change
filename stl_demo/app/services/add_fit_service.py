from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import trimesh

from app.config import settings
from app.services.add_mount_planner import AddMountPlanner, AddMountPlan, MountFrame
from app.services.add_visual_scale_service import AddVisualScaleService, VisualScalePlan
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
    def __init__(
        self,
        *,
        anchor_service: Optional[GeometryAnchorService] = None,
        constraint_service: Optional[PartConstraintService] = None,
        mount_planner: Optional[AddMountPlanner] = None,
        scale_service: Optional[AddVisualScaleService] = None,
    ) -> None:
        self.anchor_service = anchor_service or GeometryAnchorService()
        self.constraint_service = constraint_service
        self.mount_planner = mount_planner or AddMountPlanner(
            anchor_service=self.anchor_service,
            constraint_service=self.constraint_service,
        )
        self.scale_service = scale_service or AddVisualScaleService()

    def _normalize(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _mesh_bounds_center(self, mesh: trimesh.Trimesh) -> np.ndarray:
        b = mesh.bounds
        return (b[0] + b[1]) / 2.0

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

    def _orient_source_to_frame(self, mesh: trimesh.Trimesh, frame: MountFrame) -> None:
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

    def _apply_scale_plan(self, mesh: trimesh.Trimesh, scale_plan: VisualScalePlan, warnings: List[str]) -> Dict[str, Any]:
        applied: Dict[str, Any] = {
            "uniform_scale_applied": 1.0,
            "axis_stretch_applied": None,
        }
        center = self._mesh_bounds_center(mesh)
        if abs(scale_plan.uniform_scale_factor - 1.0) > 1e-9:
            mat = self._uniform_scale_matrix_about_point(
                scale_factor=float(scale_plan.uniform_scale_factor),
                anchor_point=center,
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
                anchor_point=self._mesh_bounds_center(mesh),
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

    def _place_mesh_on_frame(
        self,
        mesh: trimesh.Trimesh,
        *,
        frame: MountFrame,
        clearance_mm: float,
    ) -> Dict[str, Any]:
        normal = np.asarray(frame.normal, dtype=float)
        tangent = np.asarray(frame.tangent, dtype=float)
        bitangent = np.asarray(frame.bitangent, dtype=float)
        origin = np.asarray(frame.origin, dtype=float)

        current_n_min = self._projection_min(mesh, normal)
        current_t_center = self._projection_center(mesh, tangent)
        current_b_center = self._projection_center(mesh, bitangent)

        target_n_min = float(np.dot(origin, normal) + clearance_mm)
        target_t_center = float(np.dot(origin, tangent))
        target_b_center = float(np.dot(origin, bitangent))

        delta = (
            (target_n_min - current_n_min) * normal
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
            "target_n_min": target_n_min,
            "frame_origin": [float(x) for x in origin.tolist()],
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
            parent_mesh = self.anchor_service.load_mesh(attach_to_path)
        except Exception as exc:
            return AddFitResult(False, "", {}, f"load mesh failed: {exc}", warnings)

        resolved = self._resolve_mount_request(
            asset_metadata=asset_metadata,
            fit_policy=fit_policy,
            mount_request=mount_request,
            visual_fit=visual_fit,
        )

        mount_plan = self.mount_planner.plan_add_mount(
            attach_to=attach_to,
            attach_to_path=attach_to_path,
            mount_region=resolved["mount_region"],
            placement_scope=resolved["placement_scope"],
            preferred_strategy=resolved["preferred_strategy"],
            category=resolved["category"],
            preserve_aspect_ratio=resolved["preserve_aspect_ratio"],
            allow_axis_stretch=resolved["allow_axis_stretch"],
        )

        fitted_meshes: List[trimesh.Trimesh] = []
        frame_reports: List[Dict[str, Any]] = []

        for frame in mount_plan.frames:
            work_mesh = imported_mesh.copy()
            self._orient_source_to_frame(work_mesh, frame)

            single_frame_plan = AddMountPlan(
                mount_strategy=mount_plan.mount_strategy,
                placement_scope=mount_plan.placement_scope,
                attach_to=mount_plan.attach_to,
                frames=[frame],
                preserve_aspect_ratio=mount_plan.preserve_aspect_ratio,
                allow_axis_stretch=mount_plan.allow_axis_stretch,
                diagnostics=mount_plan.diagnostics,
            )

            scale_plan = self.scale_service.compute_visual_scale_plan(
                oriented_mesh=work_mesh,
                parent_mesh=parent_mesh,
                mount_plan=single_frame_plan,
                target_ratio=resolved["target_ratio"],
                preserve_aspect_ratio=resolved["preserve_aspect_ratio"],
                allow_axis_stretch=resolved["allow_axis_stretch"],
                allow_unlimited_upscale=resolved["allow_unlimited_upscale"],
            )
            scale_applied = self._apply_scale_plan(work_mesh, scale_plan, warnings)
            placement = self._place_mesh_on_frame(
                work_mesh,
                frame=frame,
                clearance_mm=resolved["clearance_mm"],
            )
            fitted_meshes.append(work_mesh)
            frame_reports.append(
                {
                    "frame": frame.to_dict(),
                    "scale_plan": scale_plan.to_dict(),
                    "scale_applied": scale_applied,
                    "placement": placement,
                    "final_extents": {
                        "x": float(work_mesh.extents[0]),
                        "y": float(work_mesh.extents[1]),
                        "z": float(work_mesh.extents[2]),
                    },
                }
            )

        combined = self._merge_meshes(fitted_meshes)

        primary_axis = np.asarray(mount_plan.frames[0].tangent, dtype=float)
        overrides_applied = self._apply_post_overrides(
            combined,
            post_transform_overrides=post_transform_overrides,
            primary_axis=primary_axis,
        )

        try:
            saved = self.anchor_service.save_mesh(combined, output_path)
        except Exception as exc:
            return AddFitResult(False, "", {}, f"export fitted asset failed: {exc}", warnings)

        fit_plan: Dict[str, Any] = {
            "attach_to": attach_to,
            "resolved_request": resolved,
            "mount_plan": mount_plan.to_dict(),
            "frame_reports": frame_reports,
            "asset_metadata": asset_metadata,
            "overrides_applied": overrides_applied,
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
            message="add success via regional mount planning + visual scale fitting",
            warnings=warnings,
        )
