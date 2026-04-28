from __future__ import annotations

from typing import Any, Dict, Iterable

import numpy as np
import trimesh

from app.services.add_mount_planner import MountFrame


class AssetMountAnchorService:
    def _normalize(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _project_values(self, points: np.ndarray, axis: Iterable[float]) -> np.ndarray:
        axis_vec = self._normalize(axis)
        return np.dot(points, axis_vec)

    def _select_band_points(
        self,
        points: np.ndarray,
        *,
        axis: Iterable[float],
        side: str,
        min_points: int = 30,
    ) -> Dict[str, Any]:
        proj = self._project_values(points, axis)
        v_min = float(proj.min())
        v_max = float(proj.max())
        v_span = max(v_max - v_min, 1e-9)

        band_candidates = sorted(
            {
                max(v_span * 0.01, 1.0),
                max(v_span * 0.02, 2.0),
                max(v_span * 0.04, 4.0),
                max(v_span * 0.06, 6.0),
                2.0,
                5.0,
                10.0,
                20.0,
                40.0,
            }
        )

        for band in band_candidates:
            if side == "max":
                mask = proj >= (v_max - band)
                extreme_value = v_max
            else:
                mask = proj <= (v_min + band)
                extreme_value = v_min
            selected = points[mask]
            if len(selected) >= min_points:
                return {
                    "success": True,
                    "points": selected,
                    "band_mm": float(band),
                    "extreme_value": float(extreme_value),
                }

        order = np.argsort(proj)
        take_n = min(max(min_points, int(len(points) * 0.02)), len(points))
        if side == "max":
            selected = points[order[-take_n:]]
            extreme_value = v_max
        else:
            selected = points[order[:take_n]]
            extreme_value = v_min

        return {
            "success": True,
            "points": selected,
            "band_mm": float(band_candidates[0]) if band_candidates else 0.0,
            "extreme_value": float(extreme_value),
        }

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
        }

    def _compute_projected_center(
        self,
        points: np.ndarray,
        *,
        tangent: Iterable[float],
        bitangent: Iterable[float],
    ) -> Dict[str, float]:
        proj_t = self._project_values(points, tangent)
        proj_b = self._project_values(points, bitangent)
        return {
            "t_center": 0.5 * (float(proj_t.min()) + float(proj_t.max())),
            "b_center": 0.5 * (float(proj_b.min()) + float(proj_b.max())),
        }

    def _compute_inplane_axis(
        self,
        points: np.ndarray,
        *,
        tangent: Iterable[float],
        bitangent: Iterable[float],
    ) -> np.ndarray:
        tangent = self._normalize(tangent)
        bitangent = self._normalize(bitangent)

        if points.size == 0 or len(points) < 3:
            return tangent

        proj_t = self._project_values(points, tangent)
        proj_b = self._project_values(points, bitangent)
        coords = np.stack([proj_t, proj_b], axis=1)
        cov = np.cov(coords.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        axis_2d = eigvecs[:, int(np.argmax(eigvals))]
        axis = axis_2d[0] * tangent + axis_2d[1] * bitangent
        axis = self._normalize(axis)
        if float(np.dot(axis, tangent)) < 0:
            axis = -axis
        return axis

    def analyze_oriented_asset(
        self,
        mesh: trimesh.Trimesh,
        *,
        frame: MountFrame,
        mount_strategy: str,
    ) -> Dict[str, Any]:
        verts = np.asarray(mesh.vertices, dtype=float)
        normal = np.asarray(frame.normal, dtype=float)
        tangent = np.asarray(frame.tangent, dtype=float)
        bitangent = np.asarray(frame.bitangent, dtype=float)

        support_patch = self._select_band_points(
            verts,
            axis=normal,
            side="min",
            min_points=30,
        )
        support_points = np.asarray(support_patch["points"], dtype=float)
        support_plane = self._fit_plane_normal(
            support_points,
            preferred_normal=normal,
        )
        support_proj = self._project_values(support_points, normal)
        support_level_mean = float(np.mean(support_proj)) if len(support_proj) else 0.0
        support_level_min = float(np.min(support_proj)) if len(support_proj) else 0.0

        if mount_strategy == "top_cover":
            placement_patch = self._select_band_points(
                verts,
                axis=normal,
                side="max",
                min_points=30,
            )
            placement_source = "top_patch"
        else:
            placement_patch = support_patch
            placement_source = "attachment_patch"

        placement_points = np.asarray(placement_patch["points"], dtype=float)
        center_2d = self._compute_projected_center(
            placement_points,
            tangent=tangent,
            bitangent=bitangent,
        )
        placement_t_center = float(center_2d["t_center"])
        placement_b_center = float(center_2d["b_center"])

        placement_normal_level = float(np.mean(self._project_values(placement_points, normal)))
        placement_center_3d = (
            tangent * placement_t_center
            + bitangent * placement_b_center
            + normal * placement_normal_level
        )

        inplane_axis = self._compute_inplane_axis(
            placement_points,
            tangent=tangent,
            bitangent=bitangent,
        )

        return {
            "placement_t_center": placement_t_center,
            "placement_b_center": placement_b_center,
            "placement_center_3d": placement_center_3d,
            "alignment_center": placement_center_3d,
            "inplane_axis": inplane_axis,
            "support_level_mean": support_level_mean,
            "support_level_min": support_level_min,
            "support_points": support_points,
            "support_plane_normal": support_plane["plane_normal"],
            "support_plane_spread_mm": float(support_plane["spread_mm"]),
            "report": {
                "placement_source": placement_source,
                "placement_point_count": int(len(placement_points)),
                "placement_band_mm": float(placement_patch["band_mm"]),
                "support_point_count": int(len(support_points)),
                "support_band_mm": float(support_patch["band_mm"]),
                "support_plane_spread_mm": float(support_plane["spread_mm"]),
                "placement_center_3d": [float(x) for x in placement_center_3d.tolist()],
                "support_level_mean": support_level_mean,
                "support_level_min": support_level_min,
                "inplane_axis": [float(x) for x in inplane_axis.tolist()],
            },
        }