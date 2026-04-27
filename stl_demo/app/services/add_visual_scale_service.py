from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, Optional

import numpy as np
import trimesh

from app.services.add_mount_planner import AddMountPlan, MountFrame


@dataclass
class VisualScalePlan:
    scale_mode: str
    uniform_scale_factor: float
    axis_stretch: Dict[str, Any] | None
    target_metrics: Dict[str, Any]
    source_metrics: Dict[str, Any]
    diagnostics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AddVisualScaleService:
    def _normalize(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _extent_along_axis(self, mesh: trimesh.Trimesh, axis: Iterable[float]) -> float:
        axis_vec = self._normalize(axis)
        proj = np.dot(mesh.vertices, axis_vec)
        return float(proj.max() - proj.min())

    def _pick_primary_frame(self, mount_plan: AddMountPlan) -> MountFrame:
        if not mount_plan.frames:
            raise ValueError("mount_plan.frames is empty")
        return mount_plan.frames[0]

    def compute_visual_scale_plan(
        self,
        *,
        oriented_mesh: trimesh.Trimesh,
        parent_mesh: trimesh.Trimesh,
        mount_plan: AddMountPlan,
        target_ratio: float,
        preserve_aspect_ratio: bool = True,
        allow_axis_stretch: bool = True,
        allow_unlimited_upscale: bool = True,
    ) -> VisualScalePlan:
        frame = self._pick_primary_frame(mount_plan)
        strategy = mount_plan.mount_strategy

        src_t = max(self._extent_along_axis(oriented_mesh, frame.tangent), 1e-9)
        src_b = max(self._extent_along_axis(oriented_mesh, frame.bitangent), 1e-9)
        src_n = max(self._extent_along_axis(oriented_mesh, frame.normal), 1e-9)

        target_ratio = float(target_ratio or 1.0)
        target_t = max(frame.tangent_span * target_ratio, 1e-9)
        target_b = max(frame.bitangent_span * target_ratio, 1e-9)

        diagnostics: Dict[str, Any] = {
            "allow_unlimited_upscale": bool(allow_unlimited_upscale),
            "preserve_aspect_ratio": bool(preserve_aspect_ratio),
            "allow_axis_stretch": bool(allow_axis_stretch),
        }
        axis_stretch: Optional[Dict[str, Any]] = None

        if strategy in {"top_cover", "side_panel", "rear_frame"}:
            raw_t = target_t / src_t
            raw_b = target_b / src_b
            uniform = min(raw_t, raw_b) if preserve_aspect_ratio else raw_t
            uniform = float(max(uniform, 1e-9))
            diagnostics["raw_scale_factor_tangent"] = float(raw_t)
            diagnostics["raw_scale_factor_bitangent"] = float(raw_b)

            if allow_axis_stretch:
                after_t = src_t * uniform
                after_b = src_b * uniform
                need_t = target_t / max(after_t, 1e-9)
                need_b = target_b / max(after_b, 1e-9)
                if need_t > 1.02 and need_t >= need_b:
                    axis_stretch = {
                        "axis_vector": list(map(float, frame.tangent)),
                        "scale_factor": float(need_t),
                        "target_after_uniform": float(target_t),
                        "source_after_uniform": float(after_t),
                        "reason": "match_tangent_span",
                    }
                elif need_b > 1.02:
                    axis_stretch = {
                        "axis_vector": list(map(float, frame.bitangent)),
                        "scale_factor": float(need_b),
                        "target_after_uniform": float(target_b),
                        "source_after_uniform": float(after_b),
                        "reason": "match_bitangent_span",
                    }
            scale_mode = f"{strategy}_projection"

        elif strategy == "perimeter_wrap":
            raw_t = target_t / src_t
            raw_b = target_b / src_b
            uniform = max(raw_t, raw_b) if preserve_aspect_ratio else raw_t
            uniform = float(max(uniform, 1e-9))
            diagnostics["raw_scale_factor_tangent"] = float(raw_t)
            diagnostics["raw_scale_factor_bitangent"] = float(raw_b)
            scale_mode = "fit_perimeter_span"
        else:
            raw_t = target_t / src_t
            uniform = float(max(raw_t, 1e-9))
            diagnostics["raw_scale_factor_tangent"] = float(raw_t)
            scale_mode = "generic_projection"

        return VisualScalePlan(
            scale_mode=scale_mode,
            uniform_scale_factor=uniform,
            axis_stretch=axis_stretch,
            target_metrics={
                "target_tangent_span": float(target_t),
                "target_bitangent_span": float(target_b),
            },
            source_metrics={
                "source_tangent_span": float(src_t),
                "source_bitangent_span": float(src_b),
                "source_normal_span": float(src_n),
            },
            diagnostics=diagnostics,
        )
