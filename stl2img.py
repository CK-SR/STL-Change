import math
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

import trimesh
import pyrender


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def load_mesh_from_stl(stl_path):
    """
    读取 STL，统一返回 trimesh.Trimesh
    """
    mesh = trimesh.load(stl_path, force='mesh')

    if isinstance(mesh, trimesh.Scene):
        geoms = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geoms:
            raise ValueError(f"No valid geometry in scene: {stl_path}")
        mesh = trimesh.util.concatenate(geoms)

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"Unsupported mesh type: {type(mesh)}")

    if mesh.vertices.shape[0] == 0 or mesh.faces.shape[0] == 0:
        raise ValueError(f"Invalid mesh: {stl_path}")

    try:
        mesh.fix_normals()
    except Exception:
        pass

    return mesh


def normalize_group_meshes(meshes, target_extent=1.0):
    """
    对整组 mesh 做整体居中和统一缩放，
    保留各个 STL 之间的相对位置关系
    """
    meshes = [m.copy() for m in meshes]
    all_vertices = np.vstack([m.vertices for m in meshes])

    min_corner = all_vertices.min(axis=0)
    max_corner = all_vertices.max(axis=0)
    center = (min_corner + max_corner) / 2.0
    extents = max_corner - min_corner
    max_extent = float(np.max(extents))

    for m in meshes:
        m.apply_translation(-center)
        if max_extent > 1e-8:
            m.apply_scale(target_extent / max_extent)

    return meshes


def trimesh_to_pyrender_mesh(mesh, color=(0.7, 0.8, 0.95, 1.0)):
    material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=color,
        metallicFactor=0.1,
        roughnessFactor=0.8
    )
    return pyrender.Mesh.from_trimesh(mesh, material=material, smooth=False)


def normalize(v):
    n = np.linalg.norm(v)
    if n < 1e-12:
        return v
    return v / n


def look_at(camera_position, target, up=np.array([0.0, 0.0, 1.0])):
    """
    构造 camera pose (camera -> world)
    """
    camera_position = np.asarray(camera_position, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    forward = normalize(target - camera_position)
    right = normalize(np.cross(forward, up))
    if np.linalg.norm(right) < 1e-8:
        alt_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        right = normalize(np.cross(forward, alt_up))
    true_up = normalize(np.cross(right, forward))

    pose = np.eye(4, dtype=np.float64)
    pose[:3, 0] = right
    pose[:3, 1] = true_up
    pose[:3, 2] = -forward
    pose[:3, 3] = camera_position
    return pose


def orbit_camera_pose(distance, elev_deg, azim_deg, target=(0, 0, 0)):
    """
    生成斜视图相机姿态
    """
    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)

    x = distance * math.cos(elev) * math.cos(azim)
    y = distance * math.cos(elev) * math.sin(azim)
    z = distance * math.sin(elev)

    cam_pos = np.array([x, y, z], dtype=np.float64)
    target = np.array(target, dtype=np.float64)
    return look_at(cam_pos, target)


def create_scene(bg_color=(255, 255, 255, 255), ambient=(0.18, 0.18, 0.18)):
    scene = pyrender.Scene(
        bg_color=np.array(bg_color) / 255.0,
        ambient_light=np.array(ambient)
    )
    return scene


def add_default_lights(scene):
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=2.5)

    light_poses = [
        look_at(np.array([2.5, 2.5, 3.0]), np.zeros(3)),
        look_at(np.array([-2.5, -1.5, 2.0]), np.zeros(3)),
        look_at(np.array([1.5, -2.5, 1.5]), np.zeros(3)),
    ]

    for pose in light_poses:
        scene.add(light, pose=pose)


def render_scene_to_image(scene, camera_pose, width=1200, height=1200, yfov=np.pi / 3.0):
    camera = pyrender.PerspectiveCamera(yfov=yfov)
    cam_node = scene.add(camera, pose=camera_pose)

    renderer = pyrender.OffscreenRenderer(viewport_width=width, viewport_height=height)
    color, depth = renderer.render(scene)
    renderer.delete()

    scene.remove_node(cam_node)

    return Image.fromarray(color)


def render_group_isometric(stl_paths, out_path, image_size=1200, target_extent=1.0):
    meshes = []
    valid_names = []

    for p in stl_paths:
        try:
            mesh = load_mesh_from_stl(p)
            meshes.append(mesh)
            valid_names.append(Path(p).stem)
        except Exception as e:
            print(f"[WARN] Skip {p}: {e}")

    if not meshes:
        print("[ERROR] No valid STL files found.")
        return

    meshes = normalize_group_meshes(meshes, target_extent=target_extent)

    scene = create_scene()
    add_default_lights(scene)

    palette = [
        (0.88, 0.35, 0.35, 1.0),
        (0.35, 0.55, 0.88, 1.0),
        (0.35, 0.75, 0.45, 1.0),
        (0.88, 0.65, 0.30, 1.0),
        (0.65, 0.45, 0.88, 1.0),
        (0.30, 0.75, 0.75, 1.0),
        (0.80, 0.50, 0.60, 1.0),
        (0.55, 0.55, 0.55, 1.0),
    ]

    for i, mesh in enumerate(meshes):
        color = palette[i % len(palette)]
        scene.add(trimesh_to_pyrender_mesh(mesh, color=color))

    # 这里只保留一个斜视图
    cam_pose = orbit_camera_pose(
        distance=1.8,   # 相机距离
        elev_deg=28,    # 仰角
        azim_deg=45     # 方位角
    )

    img = render_scene_to_image(
        scene,
        cam_pose,
        width=image_size,
        height=image_size
    )
    img.save(out_path)
    print(f"[INFO] Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Render one group isometric overview for STL files.")
    parser.add_argument("--input_dir", type=str, required=True, help="包含 STL 的目录")
    parser.add_argument("--output_path", type=str, default="group_isometric.png", help="输出图片路径")
    parser.add_argument("--image_size", type=int, default=1200, help="输出图像尺寸")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    stl_paths = sorted(list(input_dir.glob("*.stl")) + list(input_dir.glob("*.STL")))

    if not stl_paths:
        print(f"[ERROR] No STL files found in: {input_dir}")
        return

    out_path = Path(args.output_path)
    ensure_dir(out_path.parent)

    print(f"[INFO] Found {len(stl_paths)} STL files.")
    render_group_isometric(
        [str(p) for p in stl_paths],
        out_path=str(out_path),
        image_size=args.image_size
    )


if __name__ == "__main__":
    main()