from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import trimesh
from PIL import Image, ImageDraw


@dataclass
class FinalRenderResult:
    success: bool
    image_path: str
    rendered_parts: list[str]
    changed_parts: list[str]
    message: str
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize(vec: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(vec), dtype=np.float64).reshape(3)
    norm = np.linalg.norm(arr)
    if norm < 1e-9:
        raise ValueError(f"Invalid vector: {vec}")
    return arr / norm


def _look_at(
    camera_position: np.ndarray,
    target: np.ndarray,
    up: np.ndarray = np.asarray([0.0, 0.0, 1.0], dtype=np.float64),
) -> np.ndarray:
    camera_position = np.asarray(camera_position, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    forward = _normalize(target - camera_position)
    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-8:
        right = np.cross(forward, np.asarray([0.0, 1.0, 0.0], dtype=np.float64))
    right = _normalize(right)
    true_up = _normalize(np.cross(right, forward))

    pose = np.eye(4, dtype=np.float64)
    pose[:3, 0] = right
    pose[:3, 1] = true_up
    pose[:3, 2] = -forward
    pose[:3, 3] = camera_position
    return pose


def _orbit_camera_pose(
    *,
    distance: float,
    elev_deg: float,
    azim_deg: float,
    target: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)
    x = distance * math.cos(elev) * math.cos(azim)
    y = distance * math.cos(elev) * math.sin(azim)
    z = distance * math.sin(elev)
    return _look_at(np.asarray([x, y, z], dtype=np.float64), np.asarray(target, dtype=np.float64))


def _load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load_mesh(path, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            raise ValueError(f"no mesh geometry in {path}")
        return trimesh.util.concatenate(meshes)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"unsupported mesh type for {path}: {type(loaded).__name__}")
    if loaded.vertices is None or len(loaded.vertices) == 0:
        raise ValueError(f"empty mesh: {path}")
    return loaded


def _normalize_meshes(meshes: Sequence[trimesh.Trimesh], target_extent: float = 1.0) -> list[trimesh.Trimesh]:
    copies = [mesh.copy() for mesh in meshes]
    all_vertices = np.vstack([mesh.vertices for mesh in copies])
    min_corner = all_vertices.min(axis=0)
    max_corner = all_vertices.max(axis=0)
    center = (min_corner + max_corner) / 2.0
    extents = max_corner - min_corner
    max_extent = float(np.max(extents))

    for mesh in copies:
        mesh.apply_translation(-center)
        if max_extent > 1e-8:
            mesh.apply_scale(target_extent / max_extent)
    return copies


def _to_pyrender_mesh(mesh: trimesh.Trimesh, color: tuple[float, float, float, float]):
    import pyrender

    material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=color,
        metallicFactor=0.05,
        roughnessFactor=0.85,
    )
    return pyrender.Mesh.from_trimesh(mesh, material=material, smooth=False)


def _part_keys(path: Path) -> set[str]:
    return {path.name, path.stem}


def render_final_stl_scene(
    *,
    final_stl_dir: Path,
    output_image_path: Path,
    changed_parts: set[str] | None = None,
    image_size: int = 1400,
) -> FinalRenderResult:
    """
    Render the final full STL bundle: changed/new parts are highlighted in red,
    unchanged original parts remain neutral gray.
    """
    warnings: list[str] = []
    changed_parts = set(changed_parts or set())
    stl_paths = sorted(final_stl_dir.glob("*.stl"))
    if not stl_paths:
        return FinalRenderResult(
            success=False,
            image_path="",
            rendered_parts=[],
            changed_parts=sorted(changed_parts),
            message=f"no STL files found under {final_stl_dir}",
            warnings=warnings,
        )

    meshes: list[trimesh.Trimesh] = []
    mesh_paths: list[Path] = []
    for path in stl_paths:
        try:
            meshes.append(_load_mesh(path))
            mesh_paths.append(path)
        except Exception as exc:
            warnings.append(f"render_skip[{path.name}]={exc}")

    if not meshes:
        return FinalRenderResult(
            success=False,
            image_path="",
            rendered_parts=[],
            changed_parts=sorted(changed_parts),
            message="no renderable STL meshes found",
            warnings=warnings,
        )

    import pyrender

    try:
        output_image_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_meshes = _normalize_meshes(meshes, target_extent=1.0)
        scene = pyrender.Scene(
            bg_color=[1.0, 1.0, 1.0, 1.0],
            ambient_light=[0.38, 0.38, 0.38],
        )

        changed_rendered: list[str] = []
        for path, mesh in zip(mesh_paths, normalized_meshes):
            is_changed = bool(_part_keys(path) & changed_parts)
            if is_changed:
                changed_rendered.append(path.name)
            color = (0.9, 0.24, 0.18, 1.0) if is_changed else (0.62, 0.64, 0.66, 1.0)
            scene.add(_to_pyrender_mesh(mesh, color))

        light_pose = np.eye(4, dtype=np.float64)
        light_pose[:3, 3] = [1.0, -1.0, 2.0]
        scene.add(pyrender.DirectionalLight(color=np.ones(3), intensity=3.0), pose=light_pose)
        fill_pose = np.eye(4, dtype=np.float64)
        fill_pose[:3, 3] = [-1.0, 1.0, 1.2]
        scene.add(pyrender.DirectionalLight(color=np.ones(3), intensity=1.6), pose=fill_pose)

        camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
        camera_pose = _orbit_camera_pose(distance=1.85, elev_deg=28.0, azim_deg=45.0)
        scene.add(camera, pose=camera_pose)

        renderer = pyrender.OffscreenRenderer(viewport_width=image_size, viewport_height=image_size)
        color, _depth = renderer.render(scene)
        renderer.delete()

        image = Image.fromarray(color)
        draw = ImageDraw.Draw(image)
        legend = "Final STL scene: red=changed/new parts, gray=unchanged original parts"
        draw.rectangle((12, 12, 740, 52), fill=(255, 255, 255))
        draw.text((24, 24), legend, fill=(0, 0, 0))
        image.save(output_image_path)

        return FinalRenderResult(
            success=True,
            image_path=str(output_image_path),
            rendered_parts=[path.name for path in mesh_paths],
            changed_parts=sorted(changed_rendered),
            message="final STL scene rendered",
            warnings=warnings,
        )
    except Exception as exc:
        warnings.append(f"final_render_failed={exc}")
        return FinalRenderResult(
            success=False,
            image_path="",
            rendered_parts=[path.name for path in mesh_paths],
            changed_parts=sorted(changed_parts),
            message="final STL scene render failed",
            warnings=warnings,
        )
