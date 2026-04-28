from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import trimesh

from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService
from app.services.add_mount_planner import MountFrame


@dataclass
class ParentMountSurface:
    origin: List[float]
    normal: List[float]
    tangent: List[float]
    bitangent: List[float]
    region_name: str
    role: str
    tangent_span: float
    bitangent_span: float
    footprint_bounds: Dict[str, float]
    diagnostics: Dict[str, Any]

    def to_mount_frame(self) -> MountFrame:
        return MountFrame(
            origin=self.origin,
            normal=self.normal,
            tangent=self.tangent,
            bitangent=self.bitangent,
            region_name=self.region_name,
            role=self.role,
            tangent_span=self.tangent_span,
            bitangent_span=self.bitangent_span,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParentMountSurfacePlan:
    mount_strategy: str
    placement_scope: str
    attach_to: str
    surfaces: List[ParentMountSurface]
    diagnostics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mount_strategy": self.mount_strategy,
            "placement_scope": self.placement_scope,
            "attach_to": self.attach_to,
            "surfaces": [x.to_dict() for x in self.surfaces],
            "diagnostics": self.diagnostics,
        }


class ParentMountSurfaceService:
    def __init__(
        self,
        *,
        anchor_service: Optional[GeometryAnchorService] = None,
        constraint_service: Optional[PartConstraintService] = None,
    ) -> None:
        self.anchor_service = anchor_service or GeometryAnchorService()
        self.constraint_service = constraint_service

    def _normalize(self, vec: np.ndarray | List[float]) -> np.ndarray:
        arr = np.asarray(vec, dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _project_values(self, points: np.ndarray, axis: np.ndarray) -> np.ndarray:
        axis = self._normalize(axis)
        return np.dot(points, axis)

    def _project_extent(self, mesh: trimesh.Trimesh, axis: np.ndarray) -> float:
        axis = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis)
        return float(proj.max() - proj.min())

    def _project_max(self, mesh: trimesh.Trimesh, axis: np.ndarray) -> float:
        axis = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis)
        return float(proj.max())

    def _project_min(self, mesh: trimesh.Trimesh, axis: np.ndarray) -> float:
        axis = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis)
        return float(proj.min())

    def _project_center(self, mesh: trimesh.Trimesh, axis: np.ndarray) -> float:
        axis = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis)
        return float((proj.min() + proj.max()) * 0.5)

    def _center_of_mesh(self, mesh: trimesh.Trimesh) -> np.ndarray:
        b = mesh.bounds
        return (b[0] + b[1]) / 2.0

    def _infer_primary_axes(self, attach_to: str, mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        up = np.asarray([0.0, 0.0, 1.0], dtype=float)

        axis = None
        if self.constraint_service is not None:
            try:
                axis = np.asarray(self.constraint_service.get_primary_axis(attach_to), dtype=float)
            except Exception:
                axis = None

        if axis is None or np.linalg.norm(axis) < 1e-9:
            ext = np.asarray(mesh.extents, dtype=float)
            axis = (
                np.asarray([1.0, 0.0, 0.0], dtype=float)
                if ext[0] >= ext[1]
                else np.asarray([0.0, 1.0, 0.0], dtype=float)
            )

        axis_xy = np.asarray([axis[0], axis[1], 0.0], dtype=float)
        if np.linalg.norm(axis_xy) < 1e-9:
            axis_xy = np.asarray([1.0, 0.0, 0.0], dtype=float)
        forward = self._normalize(axis_xy)
        lateral = self._normalize(np.cross(up, forward))
        return forward, lateral, up

    def _resolve_mount_strategy(self, mount_region: str, preferred_strategy: str, category: str) -> str:
        strategy = (preferred_strategy or "").strip().lower()
        if strategy in {"top_cover", "side_panel", "perimeter_wrap", "rear_frame"}:
            return strategy

        mr = (mount_region or "").strip().lower()
        if mr in {"turret_top", "top_hull", "top", "roof"}:
            return "top_cover"
        if mr in {"hull_side", "side", "left_side", "right_side", "turret_side"}:
            return "side_panel"
        if mr in {"turret_perimeter", "perimeter", "full_perimeter", "wrap"}:
            return "perimeter_wrap"
        if mr in {"rear", "rear_hull", "tail"}:
            return "rear_frame"

        c = (category or "").strip().lower()
        if c in {"roof", "cage", "frame", "armor_cage"}:
            return "top_cover"
        if c in {"guard", "side_guard", "slat", "mesh"}:
            return "side_panel"
        if c in {"cable", "chain", "dreadlocks", "rope", "guard_net"}:
            return "perimeter_wrap"
        return "top_cover"

    def _resolve_placement_scope(self, mount_strategy: str, placement_scope: str) -> str:
        scope = (placement_scope or "").strip().lower()
        if scope:
            return scope
        if mount_strategy == "side_panel":
            return "both_sides"
        if mount_strategy == "perimeter_wrap":
            return "full_perimeter"
        return "single"

    def _make_footprint_bounds(
        self,
        *,
        center_t: float,
        center_b: float,
        tangent_span: float,
        bitangent_span: float,
    ) -> Dict[str, float]:
        return {
            "t_min": float(center_t - tangent_span * 0.5),
            "t_max": float(center_t + tangent_span * 0.5),
            "b_min": float(center_b - bitangent_span * 0.5),
            "b_max": float(center_b + bitangent_span * 0.5),
        }

    def _extract_top_cover_surface(
        self,
        mesh: trimesh.Trimesh,
        *,
        forward: np.ndarray,
        lateral: np.ndarray,
        up: np.ndarray,
    ) -> ParentMountSurface:
        verts = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        face_normals = np.asarray(mesh.face_normals, dtype=float)
        face_centers = np.asarray(mesh.triangles_center, dtype=float)

        f_span = self._project_extent(mesh, forward)
        l_span = self._project_extent(mesh, lateral)
        u_span = self._project_extent(mesh, up)
        u_max = self._project_max(mesh, up)

        source = "top_faces"
        points = np.zeros((0, 3), dtype=float)
        used_band = max(u_span * 0.18, 20.0)

        if len(face_centers) > 0 and len(face_normals) == len(face_centers):
            face_u = self._project_values(face_centers, up)
            face_up_score = np.dot(face_normals, up)
            face_mask = (face_up_score >= 0.55) & (face_u >= (u_max - used_band))
            if np.any(face_mask):
                selected_faces = faces[face_mask]
                points = verts[selected_faces.reshape(-1)]
                points = np.asarray(points, dtype=float)

        if len(points) < 60:
            source = "top_band_vertices"
            used_band = max(u_span * 0.18, 20.0)
            proj_u = self._project_values(verts, up)
            points = verts[proj_u >= (u_max - used_band)]

        if len(points) < 20:
            source = "top_half_vertices_fallback"
            proj_u = self._project_values(verts, up)
            points = verts[proj_u >= (u_max - max(u_span * 0.35, 40.0))]

        proj_f = self._project_values(points, forward)
        proj_l = self._project_values(points, lateral)

        f_low = float(np.percentile(proj_f, 2.5))
        f_high = float(np.percentile(proj_f, 97.5))
        l_low = float(np.percentile(proj_l, 2.5))
        l_high = float(np.percentile(proj_l, 97.5))

        tangent_span = max(f_high - f_low, 1.0)
        bitangent_span = max(l_high - l_low, 1.0)

        # 防止极端小 patch
        if tangent_span < max(25.0, f_span * 0.08) or bitangent_span < max(25.0, l_span * 0.08):
            source = "upper_slab_fallback"
            proj_u = self._project_values(verts, up)
            slab_band = max(u_span * 0.30, 40.0)
            slab_points = verts[proj_u >= (u_max - slab_band)]
            proj_f = self._project_values(slab_points, forward)
            proj_l = self._project_values(slab_points, lateral)
            f_low = float(np.percentile(proj_f, 2.5))
            f_high = float(np.percentile(proj_f, 97.5))
            l_low = float(np.percentile(proj_l, 2.5))
            l_high = float(np.percentile(proj_l, 97.5))
            tangent_span = max(f_high - f_low, 1.0)
            bitangent_span = max(l_high - l_low, 1.0)
            points = slab_points
            used_band = slab_band

        center_t = 0.5 * (f_low + f_high)
        center_b = 0.5 * (l_low + l_high)
        origin = (forward * center_t) + (lateral * center_b) + (up * u_max)

        return ParentMountSurface(
            origin=[float(x) for x in origin.tolist()],
            normal=[float(x) for x in up.tolist()],
            tangent=[float(x) for x in forward.tolist()],
            bitangent=[float(x) for x in lateral.tolist()],
            region_name="top_cover",
            role="primary",
            tangent_span=float(tangent_span),
            bitangent_span=float(bitangent_span),
            footprint_bounds=self._make_footprint_bounds(
                center_t=center_t,
                center_b=center_b,
                tangent_span=tangent_span,
                bitangent_span=bitangent_span,
            ),
            diagnostics={
                "origin_source": source,
                "point_count": int(len(points)),
                "band_mm": float(used_band),
                "u_max": float(u_max),
                "raw_parent_spans": {
                    "forward": float(f_span),
                    "lateral": float(l_span),
                    "up": float(u_span),
                },
            },
        )

    def plan_mount_surfaces(
        self,
        *,
        attach_to: str,
        attach_to_path: str | Path,
        mount_region: str,
        placement_scope: str = "",
        preferred_strategy: str = "",
        category: str = "",
    ) -> ParentMountSurfacePlan:
        mesh = self.anchor_service.load_mesh(attach_to_path)
        center = self._center_of_mesh(mesh)
        forward, lateral, up = self._infer_primary_axes(attach_to, mesh)

        f_span = self._project_extent(mesh, forward)
        l_span = self._project_extent(mesh, lateral)
        u_span = self._project_extent(mesh, up)

        f_center = self._project_center(mesh, forward)
        l_center = self._project_center(mesh, lateral)
        f_max = self._project_max(mesh, forward)
        f_min = self._project_min(mesh, forward)
        l_max = self._project_max(mesh, lateral)
        l_min = self._project_min(mesh, lateral)
        u_max = self._project_max(mesh, up)

        mount_strategy = self._resolve_mount_strategy(mount_region, preferred_strategy, category)
        scope = self._resolve_placement_scope(mount_strategy, placement_scope)

        surfaces: List[ParentMountSurface] = []

        if mount_strategy == "top_cover":
            surfaces.append(
                self._extract_top_cover_surface(
                    mesh,
                    forward=forward,
                    lateral=lateral,
                    up=up,
                )
            )

        elif mount_strategy == "side_panel":
            def _make_side(sign: float, role: str, region_name: str) -> ParentMountSurface:
                origin = center + lateral * (sign * l_span * 0.5)
                center_t = float(self._project_center(mesh, forward))
                center_b = float(self._project_center(mesh, up))
                return ParentMountSurface(
                    origin=[float(x) for x in origin.tolist()],
                    normal=[float(x) for x in (lateral * sign).tolist()],
                    tangent=[float(x) for x in forward.tolist()],
                    bitangent=[float(x) for x in up.tolist()],
                    region_name=region_name,
                    role=role,
                    tangent_span=float(f_span),
                    bitangent_span=float(u_span),
                    footprint_bounds=self._make_footprint_bounds(
                        center_t=center_t,
                        center_b=center_b,
                        tangent_span=f_span,
                        bitangent_span=u_span,
                    ),
                    diagnostics={"origin_source": "side_panel_bbox"},
                )

            if scope in {"left", "single"}:
                surfaces.append(_make_side(+1.0, "primary", "left_side"))
            elif scope == "right":
                surfaces.append(_make_side(-1.0, "primary", "right_side"))
            else:
                surfaces.append(_make_side(+1.0, "primary", "left_side"))
                surfaces.append(_make_side(-1.0, "mirrored", "right_side"))

        elif mount_strategy == "rear_frame":
            origin = center - forward * (f_span * 0.5)
            surfaces.append(
                ParentMountSurface(
                    origin=[float(x) for x in origin.tolist()],
                    normal=[float(x) for x in (-forward).tolist()],
                    tangent=[float(x) for x in lateral.tolist()],
                    bitangent=[float(x) for x in up.tolist()],
                    region_name="rear_frame",
                    role="primary",
                    tangent_span=float(l_span),
                    bitangent_span=float(u_span),
                    footprint_bounds=self._make_footprint_bounds(
                        center_t=float(self._project_center(mesh, lateral)),
                        center_b=float(self._project_center(mesh, up)),
                        tangent_span=l_span,
                        bitangent_span=u_span,
                    ),
                    diagnostics={"origin_source": "rear_bbox"},
                )
            )

        elif mount_strategy == "perimeter_wrap":
            hang_h = max(u_span * 0.35, 1.0)
            z_center = u_max - hang_h * 0.5

            def _edge_surface(normal: np.ndarray, region_name: str, role: str) -> ParentMountSurface:
                if np.allclose(normal, forward):
                    origin = (forward * f_max) + (lateral * l_center) + (up * z_center)
                    tangent = lateral
                    tangent_span = l_span
                    center_t = l_center
                elif np.allclose(normal, -forward):
                    origin = (forward * f_min) + (lateral * l_center) + (up * z_center)
                    tangent = lateral
                    tangent_span = l_span
                    center_t = l_center
                elif np.allclose(normal, lateral):
                    origin = (forward * f_center) + (lateral * l_max) + (up * z_center)
                    tangent = forward
                    tangent_span = f_span
                    center_t = f_center
                else:
                    origin = (forward * f_center) + (lateral * l_min) + (up * z_center)
                    tangent = forward
                    tangent_span = f_span
                    center_t = f_center

                center_b = z_center
                return ParentMountSurface(
                    origin=[float(x) for x in origin.tolist()],
                    normal=[float(x) for x in normal.tolist()],
                    tangent=[float(x) for x in tangent.tolist()],
                    bitangent=[float(x) for x in up.tolist()],
                    region_name=region_name,
                    role=role,
                    tangent_span=float(tangent_span),
                    bitangent_span=float(hang_h),
                    footprint_bounds=self._make_footprint_bounds(
                        center_t=center_t,
                        center_b=center_b,
                        tangent_span=tangent_span,
                        bitangent_span=hang_h,
                    ),
                    diagnostics={"origin_source": "perimeter_bbox"},
                )

            if scope == "single":
                surfaces.append(_edge_surface(-forward, "perimeter_single", "primary"))
            else:
                surfaces.extend(
                    [
                        _edge_surface(forward, "front_perimeter", "segment_front"),
                        _edge_surface(-forward, "rear_perimeter", "segment_rear"),
                        _edge_surface(lateral, "left_perimeter", "segment_left"),
                        _edge_surface(-lateral, "right_perimeter", "segment_right"),
                    ]
                )

        diagnostics = {
            "mount_region": mount_region,
            "resolved_mount_strategy": mount_strategy,
            "resolved_placement_scope": scope,
            "parent_spans": {
                "forward": float(f_span),
                "lateral": float(l_span),
                "up": float(u_span),
            },
            "forward_axis": [float(x) for x in forward.tolist()],
            "lateral_axis": [float(x) for x in lateral.tolist()],
            "up_axis": [float(x) for x in up.tolist()],
        }

        return ParentMountSurfacePlan(
            mount_strategy=mount_strategy,
            placement_scope=scope,
            attach_to=attach_to,
            surfaces=surfaces,
            diagnostics=diagnostics,
        )