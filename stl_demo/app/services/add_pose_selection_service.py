from __future__ import annotations

import base64
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
import trimesh
from openai import OpenAI

from app.config import get_openai_api_key, settings

MIN_POSE_CANDIDATES_PER_ASSET = 12


@dataclass
class PoseCandidate:
    candidate_id: str
    mesh: trimesh.Trimesh
    transform: np.ndarray
    description: str
    geometry_report: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "transform": self.transform.tolist(),
            "description": self.description,
            "geometry_report": self.geometry_report,
        }


@dataclass
class PoseSelectionResult:
    enabled: bool
    selected_candidate_id: str
    selected_index: int
    candidates: List[Dict[str, Any]]
    scores: List[Dict[str, Any]]
    render_paths: List[str]
    message: str
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VisionPoseSelectionService:
    """
    Render multiple fitted pose candidates and ask a vision-capable OpenAI-compatible
    model to pick the most semantically plausible add/top_cover posture.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        image_size: int | None = None,
        render_dir: str | Path | None = None,
    ) -> None:
        self.base_url = base_url or settings.base_url
        self.api_key = (api_key if api_key is not None else get_openai_api_key()).strip()
        self.model_name = model_name or settings.add_vision_pose_model_name
        self.image_size = int(image_size or settings.add_vision_pose_image_size)
        self.render_dir = Path(render_dir or settings.add_vision_pose_render_dir)

    def _normalize(self, vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=float).reshape(3)
        norm = np.linalg.norm(arr)
        if norm < 1e-9:
            raise ValueError(f"Invalid vector: {vec}")
        return arr / norm

    def _rotation_matrix_about_axis(
        self,
        *,
        axis: Iterable[float],
        angle_deg: float,
        origin: Iterable[float],
    ) -> np.ndarray:
        axis_vec = self._normalize(axis)
        origin_vec = np.asarray(list(origin), dtype=float).reshape(3)
        angle = math.radians(float(angle_deg))
        ux, uy, uz = axis_vec
        c = math.cos(angle)
        s = math.sin(angle)
        r = np.asarray(
            [
                [c + ux * ux * (1 - c), ux * uy * (1 - c) - uz * s, ux * uz * (1 - c) + uy * s],
                [uy * ux * (1 - c) + uz * s, c + uy * uy * (1 - c), uy * uz * (1 - c) - ux * s],
                [uz * ux * (1 - c) - uy * s, uz * uy * (1 - c) + ux * s, c + uz * uz * (1 - c)],
            ],
            dtype=float,
        )
        mat = np.eye(4, dtype=float)
        mat[:3, :3] = r
        translate_to = np.eye(4, dtype=float)
        translate_to[:3, 3] = -origin_vec
        translate_back = np.eye(4, dtype=float)
        translate_back[:3, 3] = origin_vec
        return translate_back @ mat @ translate_to

    def build_candidate_seed_transforms(
        self,
        *,
        normal: Iterable[float],
        tangent: Iterable[float],
        bitangent: Iterable[float],
        origin: Iterable[float],
        max_candidates: int,
    ) -> List[Dict[str, Any]]:
        """
        Candidate posture transforms are intentionally applied before downstream scale
        and placement. This keeps the existing sizing/anchoring pipeline intact while
        allowing semantic roll/yaw/pitch alternatives to be compared visually.
        """
        specs = [
            ("pose_base", [], "existing geometry-aligned pose"),
            ("yaw_90", [(normal, 90.0)], "rotate in mounting plane by 90 degrees"),
            ("yaw_180", [(normal, 180.0)], "rotate in mounting plane by 180 degrees"),
            ("yaw_270", [(normal, 270.0)], "rotate in mounting plane by 270 degrees"),
            ("roll_180", [(tangent, 180.0)], "flip around tangent axis"),
            ("pitch_180", [(bitangent, 180.0)], "flip around bitangent axis"),
            ("roll_180_yaw_90", [(tangent, 180.0), (normal, 90.0)], "flip around tangent then yaw 90 degrees"),
            ("pitch_180_yaw_90", [(bitangent, 180.0), (normal, 90.0)], "flip around bitangent then yaw 90 degrees"),
            ("roll_90", [(tangent, 90.0)], "stand candidate by rolling 90 degrees around tangent"),
            ("roll_270", [(tangent, 270.0)], "stand candidate by rolling 270 degrees around tangent"),
            ("pitch_90", [(bitangent, 90.0)], "stand candidate by pitching 90 degrees around bitangent"),
            ("pitch_270", [(bitangent, 270.0)], "stand candidate by pitching 270 degrees around bitangent"),
        ]

        candidates: List[Dict[str, Any]] = []
        requested_count = max(MIN_POSE_CANDIDATES_PER_ASSET, int(max_candidates))
        for candidate_id, rotations, description in specs[:requested_count]:
            mat = np.eye(4, dtype=float)
            for axis, angle_deg in rotations:
                mat = self._rotation_matrix_about_axis(axis=axis, angle_deg=angle_deg, origin=origin) @ mat
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "transform": mat,
                    "description": description,
                    "rotations": [
                        {"axis": list(map(float, axis)), "angle_deg": float(angle_deg)}
                        for axis, angle_deg in rotations
                    ],
                }
            )
        return candidates

    def _normalize_group_meshes(self, meshes: Sequence[trimesh.Trimesh], target_extent: float = 1.0) -> List[trimesh.Trimesh]:
        meshes_copy = [m.copy() for m in meshes]
        all_vertices = np.vstack([m.vertices for m in meshes_copy])
        min_corner = all_vertices.min(axis=0)
        max_corner = all_vertices.max(axis=0)
        center = (min_corner + max_corner) / 2.0
        extents = max_corner - min_corner
        max_extent = float(np.max(extents))

        for mesh in meshes_copy:
            mesh.apply_translation(-center)
            if max_extent > 1e-8:
                mesh.apply_scale(target_extent / max_extent)
        return meshes_copy

    def _trimesh_to_pyrender_mesh(self, mesh: trimesh.Trimesh, color: tuple[float, float, float, float]):
        import pyrender

        material = pyrender.MetallicRoughnessMaterial(
            baseColorFactor=color,
            metallicFactor=0.1,
            roughnessFactor=0.8,
        )
        return pyrender.Mesh.from_trimesh(mesh, material=material, smooth=False)

    def _look_at(
        self,
        camera_position: np.ndarray,
        target: np.ndarray,
        up: np.ndarray = np.asarray([0.0, 0.0, 1.0], dtype=np.float64),
    ) -> np.ndarray:
        camera_position = np.asarray(camera_position, dtype=np.float64)
        target = np.asarray(target, dtype=np.float64)
        up = np.asarray(up, dtype=np.float64)

        forward = self._normalize(target - camera_position)
        right = self._normalize(np.cross(forward, up))
        if np.linalg.norm(right) < 1e-8:
            alt_up = np.asarray([0.0, 1.0, 0.0], dtype=np.float64)
            right = self._normalize(np.cross(forward, alt_up))
        true_up = self._normalize(np.cross(right, forward))

        pose = np.eye(4, dtype=np.float64)
        pose[:3, 0] = right
        pose[:3, 1] = true_up
        pose[:3, 2] = -forward
        pose[:3, 3] = camera_position
        return pose

    def _orbit_camera_pose(
        self,
        distance: float,
        elev_deg: float,
        azim_deg: float,
        target: tuple[float, float, float] = (0, 0, 0),
    ) -> np.ndarray:
        elev = math.radians(elev_deg)
        azim = math.radians(azim_deg)
        x = distance * math.cos(elev) * math.cos(azim)
        y = distance * math.cos(elev) * math.sin(azim)
        z = distance * math.sin(elev)
        return self._look_at(np.asarray([x, y, z], dtype=np.float64), np.asarray(target, dtype=np.float64))

    def render_candidate_image(
        self,
        *,
        parent_mesh: trimesh.Trimesh,
        candidate_mesh: trimesh.Trimesh,
        candidate_id: str,
        out_path: str | Path,
    ) -> str:
        import pyrender
        from PIL import Image, ImageDraw

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        parent_norm, candidate_norm = self._normalize_group_meshes([parent_mesh, candidate_mesh], target_extent=1.0)

        scene = pyrender.Scene(
            bg_color=np.asarray([255, 255, 255, 255], dtype=float) / 255.0,
            ambient_light=np.asarray([0.18, 0.18, 0.18], dtype=float),
        )
        light = pyrender.DirectionalLight(color=np.ones(3), intensity=2.5)
        for pose in [
            self._look_at(np.asarray([2.5, 2.5, 3.0]), np.zeros(3)),
            self._look_at(np.asarray([-2.5, -1.5, 2.0]), np.zeros(3)),
            self._look_at(np.asarray([1.5, -2.5, 1.5]), np.zeros(3)),
        ]:
            scene.add(light, pose=pose)

        scene.add(self._trimesh_to_pyrender_mesh(parent_norm, (0.55, 0.55, 0.55, 1.0)))
        scene.add(self._trimesh_to_pyrender_mesh(candidate_norm, (0.88, 0.35, 0.35, 1.0)))

        camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
        cam_pose = self._orbit_camera_pose(distance=1.25, elev_deg=28, azim_deg=45)
        cam_node = scene.add(camera, pose=cam_pose)

        renderer = pyrender.OffscreenRenderer(viewport_width=self.image_size, viewport_height=self.image_size)
        color, _depth = renderer.render(scene)
        renderer.delete()
        scene.remove_node(cam_node)

        image = Image.fromarray(color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 260, 48), fill=(255, 255, 255))
        draw.text((16, 18), f"candidate: {candidate_id}", fill=(0, 0, 0))
        image.save(out_path)
        return str(out_path)

    def _image_to_data_url(self, path: str | Path) -> str:
        data = Path(path).read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _score_with_vision_model(
        self,
        *,
        render_paths: Sequence[str],
        candidates: Sequence[PoseCandidate],
        mount_strategy: str,
        attach_to: str,
        asset_metadata: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "你是3D模型装配质检专家。请根据每张图判断红色新增资产相对于灰色父部件的姿态是否合理。"
                    "红色资产应位于父部件上方，不能歪倒、侧躺或上下颠倒；"
                    "应优先选择看起来像顶棚在父部件上方、支撑方向合理、前后左右姿态自然的候选。"
                    "请只返回JSON对象，格式为："
                    "{\"scores\":[{\"candidate_id\":\"...\",\"score\":0-100,\"reason\":\"...\"}],"
                    "\"best_candidate_id\":\"...\",\"best_reason\":\"...\"}。"
                    f"父部件: {attach_to}; mount_strategy: {mount_strategy}; asset_metadata: "
                    f"{json.dumps(asset_metadata, ensure_ascii=False)}"
                ),
            }
        ]
        for path, candidate in zip(render_paths, candidates):
            content.append({"type": "text", "text": f"候选 {candidate.candidate_id}: {candidate.description}"})
            content.append({"type": "image_url", "image_url": {"url": self._image_to_data_url(path)}})

        client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "你只输出可解析JSON，不输出Markdown。"},
                {"role": "user", "content": content},
            ],
        )
        payload = self._extract_json_object(resp.choices[0].message.content or "")
        scores = payload.get("scores", [])
        if not isinstance(scores, list):
            scores = []
        best_candidate_id = str(payload.get("best_candidate_id", "")).strip()
        best_reason = str(payload.get("best_reason", "")).strip()

        normalized_scores: List[Dict[str, Any]] = []
        known_ids = {candidate.candidate_id for candidate in candidates}
        for item in scores:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            if candidate_id not in known_ids:
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            normalized_scores.append(
                {
                    "candidate_id": candidate_id,
                    "score": max(0.0, min(100.0, score)),
                    "reason": str(item.get("reason", "")),
                }
            )

        if best_candidate_id and best_candidate_id in known_ids:
            for item in normalized_scores:
                if item["candidate_id"] == best_candidate_id:
                    item["best_candidate_from_model"] = True
                    if best_reason:
                        item["best_reason"] = best_reason
                    break
            else:
                normalized_scores.append(
                    {
                        "candidate_id": best_candidate_id,
                        "score": 100.0,
                        "reason": best_reason or "selected by model",
                        "best_candidate_from_model": True,
                    }
                )
        return normalized_scores

    def select_best_candidate(
        self,
        *,
        parent_mesh: trimesh.Trimesh,
        candidates: Sequence[PoseCandidate],
        mount_strategy: str,
        attach_to: str,
        asset_metadata: Dict[str, Any],
        run_id: str,
        force_vision: bool = False,
    ) -> PoseSelectionResult:
        warnings: List[str] = []
        vision_enabled = bool(force_vision or settings.add_vision_pose_selection_enabled)
        if not vision_enabled:
            return PoseSelectionResult(
                enabled=False,
                selected_candidate_id=candidates[0].candidate_id,
                selected_index=0,
                candidates=[candidate.to_dict() for candidate in candidates],
                scores=[],
                render_paths=[],
                message="vision pose selection disabled; using first candidate",
                warnings=warnings,
            )
        if not self.api_key:
            warnings.append("vision_pose_selection_skipped=no_api_key")
            return PoseSelectionResult(
                enabled=False,
                selected_candidate_id=candidates[0].candidate_id,
                selected_index=0,
                candidates=[candidate.to_dict() for candidate in candidates],
                scores=[],
                render_paths=[],
                message="vision pose selection skipped because API key is missing",
                warnings=warnings,
            )

        render_paths: List[str] = []
        run_dir = self.render_dir / run_id
        for candidate in candidates:
            render_paths.append(
                self.render_candidate_image(
                    parent_mesh=parent_mesh,
                    candidate_mesh=candidate.mesh,
                    candidate_id=candidate.candidate_id,
                    out_path=run_dir / f"{candidate.candidate_id}.png",
                )
            )

        scores = self._score_with_vision_model(
            render_paths=render_paths,
            candidates=candidates,
            mount_strategy=mount_strategy,
            attach_to=attach_to,
            asset_metadata=asset_metadata,
        )
        score_by_id = {item["candidate_id"]: float(item.get("score", 0.0)) for item in scores}
        selected_index = 0
        selected_score = score_by_id.get(candidates[0].candidate_id, -1.0)
        for idx, candidate in enumerate(candidates):
            score = score_by_id.get(candidate.candidate_id, -1.0)
            if score > selected_score:
                selected_index = idx
                selected_score = score

        return PoseSelectionResult(
            enabled=True,
            selected_candidate_id=candidates[selected_index].candidate_id,
            selected_index=selected_index,
            candidates=[candidate.to_dict() for candidate in candidates],
            scores=scores,
            render_paths=render_paths,
            message=f"vision pose selection chose {candidates[selected_index].candidate_id}",
            warnings=warnings,
        )
