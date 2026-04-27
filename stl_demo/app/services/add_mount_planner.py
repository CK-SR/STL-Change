from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import trimesh

from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService


@dataclass
class MountFrame:
    origin: List[float]
    normal: List[float]
    tangent: List[float]
    bitangent: List[float]
    region_name: str
    role: str
    tangent_span: float
    bitangent_span: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AddMountPlan:
    mount_strategy: str
    placement_scope: str
    attach_to: str
    frames: List[MountFrame]
    preserve_aspect_ratio: bool
    allow_axis_stretch: bool
    diagnostics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mount_strategy": self.mount_strategy,
            "placement_scope": self.placement_scope,
            "attach_to": self.attach_to,
            "frames": [x.to_dict() for x in self.frames],
            "preserve_aspect_ratio": self.preserve_aspect_ratio,
            "allow_axis_stretch": self.allow_axis_stretch,
            "diagnostics": self.diagnostics,
        }


class AddMountPlanner:
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
            axis = np.asarray([1.0, 0.0, 0.0], dtype=float) if ext[0] >= ext[1] else np.asarray([0.0, 1.0, 0.0], dtype=float)

        axis_xy = np.asarray([axis[0], axis[1], 0.0], dtype=float)
        if np.linalg.norm(axis_xy) < 1e-9:
            axis_xy = np.asarray([1.0, 0.0, 0.0], dtype=float)
        forward = self._normalize(axis_xy)
        lateral = self._normalize(np.cross(up, forward))
        return forward, lateral, up

    def _center_of_mesh(self, mesh: trimesh.Trimesh) -> np.ndarray:
        b = mesh.bounds
        return (b[0] + b[1]) / 2.0

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
        if c in {"roof", "cage", "frame"}:
            return "top_cover"
        if c in {"guard", "side_guard", "slat", "mesh"}:
            return "side_panel"
        if c in {"cable", "chain", "dreadlocks", "rope"}:
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

    def plan_add_mount(
        self,
        *,
        attach_to: str,
        attach_to_path: str | Path,
        mount_region: str,
        placement_scope: str = "",
        preferred_strategy: str = "",
        category: str = "",
        preserve_aspect_ratio: bool = True,
        allow_axis_stretch: bool = True,
    ) -> AddMountPlan:
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

        frames: List[MountFrame] = []

        if mount_strategy == "top_cover":
            origin = center.copy()
            origin[2] = u_max
            frames.append(
                MountFrame(
                    origin=origin.tolist(),
                    normal=up.tolist(),
                    tangent=forward.tolist(),
                    bitangent=lateral.tolist(),
                    region_name="top_cover",
                    role="primary",
                    tangent_span=float(f_span),
                    bitangent_span=float(l_span),
                )
            )

        elif mount_strategy == "side_panel":
            def _make_side(sign: float, role: str, region_name: str) -> MountFrame:
                origin = center + lateral * (sign * l_span * 0.5)
                return MountFrame(
                    origin=origin.tolist(),
                    normal=(lateral * sign).tolist(),
                    tangent=forward.tolist(),
                    bitangent=up.tolist(),
                    region_name=region_name,
                    role=role,
                    tangent_span=float(f_span),
                    bitangent_span=float(u_span),
                )

            if scope in {"left", "single"}:
                frames.append(_make_side(+1.0, "primary", "left_side"))
            elif scope == "right":
                frames.append(_make_side(-1.0, "primary", "right_side"))
            else:
                frames.append(_make_side(+1.0, "primary", "left_side"))
                frames.append(_make_side(-1.0, "mirrored", "right_side"))

        elif mount_strategy == "rear_frame":
            origin = center - forward * (f_span * 0.5)
            frames.append(
                MountFrame(
                    origin=origin.tolist(),
                    normal=(-forward).tolist(),
                    tangent=lateral.tolist(),
                    bitangent=up.tolist(),
                    region_name="rear_frame",
                    role="primary",
                    tangent_span=float(l_span),
                    bitangent_span=float(u_span),
                )
            )

        elif mount_strategy == "perimeter_wrap":
            hang_h = max(u_span * 0.35, 1.0)
            z_center = u_max - hang_h * 0.5

            def _edge_origin(normal: np.ndarray, span: float, region_name: str, role: str) -> MountFrame:
                if np.allclose(normal, forward):
                    origin = (forward * f_max) + (lateral * l_center) + (up * z_center)
                    tangent = lateral
                    tangent_span = l_span
                elif np.allclose(normal, -forward):
                    origin = (forward * f_min) + (lateral * l_center) + (up * z_center)
                    tangent = lateral
                    tangent_span = l_span
                elif np.allclose(normal, lateral):
                    origin = (forward * f_center) + (lateral * l_max) + (up * z_center)
                    tangent = forward
                    tangent_span = f_span
                else:
                    origin = (forward * f_center) + (lateral * l_min) + (up * z_center)
                    tangent = forward
                    tangent_span = f_span
                return MountFrame(
                    origin=origin.tolist(),
                    normal=normal.tolist(),
                    tangent=tangent.tolist(),
                    bitangent=up.tolist(),
                    region_name=region_name,
                    role=role,
                    tangent_span=float(tangent_span),
                    bitangent_span=float(hang_h),
                )

            if scope == "single":
                frames.append(_edge_origin(-forward, f_span, "perimeter_single", "primary"))
            else:
                frames.extend(
                    [
                        _edge_origin(forward, l_span, "front_perimeter", "segment_front"),
                        _edge_origin(-forward, l_span, "rear_perimeter", "segment_rear"),
                        _edge_origin(lateral, f_span, "left_perimeter", "segment_left"),
                        _edge_origin(-lateral, f_span, "right_perimeter", "segment_right"),
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
            "forward_axis": forward.tolist(),
            "lateral_axis": lateral.tolist(),
            "up_axis": up.tolist(),
        }

        return AddMountPlan(
            mount_strategy=mount_strategy,
            placement_scope=scope,
            attach_to=attach_to,
            frames=frames,
            preserve_aspect_ratio=bool(preserve_aspect_ratio),
            allow_axis_stretch=bool(allow_axis_stretch),
            diagnostics=diagnostics,
        )
