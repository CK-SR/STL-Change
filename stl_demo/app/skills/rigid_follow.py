from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from app.services.geometry_anchor_service import GeometryAnchorService


@dataclass
class RigidFollowResult:
    success: bool
    part_id: str
    output_path: Optional[str]
    detail: str
    transform_matrix: Optional[List[List[float]]] = None


def apply_rigid_transform(
    part_id: str,
    stl_path: str | Path,
    output_path: str | Path,
    transform_matrix: List[List[float]],
) -> RigidFollowResult:
    """
    对联动部件施加与主件一致的刚体变换。
    仅适用于 rigid follow，不做拉伸等非刚体联动。
    """
    gas = GeometryAnchorService()
    mesh = gas.load_mesh(stl_path)

    mat = np.asarray(transform_matrix, dtype=float)
    if mat.shape != (4, 4):
        raise ValueError(f"transform_matrix must be 4x4, got {mat.shape}")

    mesh.apply_transform(mat)
    saved = gas.save_mesh(mesh, output_path)

    return RigidFollowResult(
        success=True,
        part_id=part_id,
        output_path=saved,
        detail=f"Rigid follow transform applied to {part_id}",
        transform_matrix=mat.tolist(),
    )