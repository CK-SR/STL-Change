from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from app.config import settings


@dataclass
class AssetAcquisitionResult:
    success: bool
    message: str
    local_stl_path: str = ""
    download_url: str = ""
    task_id: str = ""
    provider_status: str = ""
    asset_metadata: Dict[str, Any] | None = None
    raw_submit_response: Dict[str, Any] | None = None
    raw_task_response: Dict[str, Any] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AssetGenerationService:
    """
    对接外部“目标结构推理智能体（素材库）”接口。

    当前支持：
    - POST /api/generate
    - GET /api/tasks/{task_id}
    - 自动闭环分支（ASSET_SELECTED / GENERATION_SUBMITTED -> SUCCESS）

    这一版的 P0 修改重点：
    1. 将 category / target_type / mount_region / placement_scope / preferred_strategy
       显式透传给远端
    2. 同时放入 metadata，便于远端保留结构化上下文
    """

    def __init__(self) -> None:
        self.base_url = settings.asset_api_base_url.rstrip("/")
        self.session = requests.Session()
        self.timeout = settings.asset_api_request_timeout_sec

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get_json(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _download_file(self, url: str, target_path: Path) -> str:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            with target_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        f.write(chunk)
        return str(target_path)

    def _extract_selected_asset(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        selected_asset = data.get("selected_asset")
        if isinstance(selected_asset, dict) and selected_asset:
            return selected_asset

        candidates = data.get("candidates") or []
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                asset = first.get("asset")
                if isinstance(asset, dict) and asset:
                    return asset
        return None

    def _poll_task_until_done(self, task_id: str) -> Dict[str, Any]:
        deadline = time.time() + settings.asset_task_poll_timeout_sec
        last_data: Dict[str, Any] = {}

        while time.time() < deadline:
            data = self._get_json(f"/api/tasks/{task_id}")
            last_data = data

            status = str(data.get("status", "")).strip().upper()

            if status in {"SUCCESS", "FAILED", "REJECTED", "CANCELLED", "PENDING_REVIEW"}:
                return data

            time.sleep(settings.asset_task_poll_interval_sec)

        raise TimeoutError(
            f"Polling asset task timeout after {settings.asset_task_poll_timeout_sec}s, "
            f"last_status={last_data.get('status')}"
        )

    def acquire_asset_stl(
        self,
        *,
        target_part: str,
        asset_request: Dict[str, Any],
        download_dir: Path,
    ) -> AssetAcquisitionResult:
        warnings: list[str] = []

        metadata = {
            "category": asset_request.get("category"),
            "target_type": asset_request.get("target_type"),
            "mount_region": asset_request.get("mount_region"),
            "placement_scope": asset_request.get("placement_scope"),
            "preferred_strategy": asset_request.get("preferred_strategy"),
        }

        payload = {
            "content": asset_request.get("content", ""),
            "input_type": asset_request.get("input_type"),
            "category": asset_request.get("category"),
            "target_type": asset_request.get("target_type"),
            "mount_region": asset_request.get("mount_region"),
            "placement_scope": asset_request.get("placement_scope"),
            "preferred_strategy": asset_request.get("preferred_strategy"),
            "metadata": metadata,
            "topk": asset_request.get("topk", settings.asset_api_topk),
            "auto_approve": asset_request.get("auto_approve", settings.asset_auto_approve),
            "auto_accept_prompt": asset_request.get(
                "auto_accept_prompt",
                settings.asset_auto_accept_prompt,
            ),
            "auto_accept_generation": asset_request.get(
                "auto_accept_generation",
                settings.asset_auto_accept_generation,
            ),
            "force_generate": asset_request.get(
                "force_generate",
                settings.asset_force_generate_default,
            ),
        }

        try:
            submit_data = self._post_json("/api/generate", payload)
        except Exception as exc:
            return AssetAcquisitionResult(
                success=False,
                message=f"asset generate request failed: {exc}",
                warnings=warnings,
            )

        status = str(submit_data.get("status", "")).strip().upper()

        if status == "ASSET_SELECTED":
            asset = self._extract_selected_asset(submit_data)
            if not asset:
                return AssetAcquisitionResult(
                    success=False,
                    message="asset generate returned ASSET_SELECTED but no selected asset found",
                    raw_submit_response=submit_data,
                    warnings=warnings,
                )

            download_url = str(asset.get("download_url", "")).strip()
            if not download_url:
                return AssetAcquisitionResult(
                    success=False,
                    message="selected asset has no download_url",
                    asset_metadata=asset,
                    raw_submit_response=submit_data,
                    warnings=warnings,
                )

            local_path = download_dir / f"{Path(target_part).stem}_{uuid.uuid4().hex}.stl"
            try:
                saved = self._download_file(download_url, local_path)
            except Exception as exc:
                return AssetAcquisitionResult(
                    success=False,
                    message=f"download selected asset failed: {exc}",
                    download_url=download_url,
                    asset_metadata=asset,
                    raw_submit_response=submit_data,
                    warnings=warnings,
                )

            return AssetAcquisitionResult(
                success=True,
                message="asset selected and downloaded",
                local_stl_path=saved,
                download_url=download_url,
                asset_metadata=asset,
                raw_submit_response=submit_data,
                warnings=warnings,
            )

        if status == "GENERATION_SUBMITTED":
            task_id = str(submit_data.get("task_id", "")).strip()
            if not task_id:
                return AssetAcquisitionResult(
                    success=False,
                    message="generation submitted but task_id missing",
                    raw_submit_response=submit_data,
                    warnings=warnings,
                )

            try:
                task_data = self._poll_task_until_done(task_id)
            except Exception as exc:
                return AssetAcquisitionResult(
                    success=False,
                    message=f"poll task failed: {exc}",
                    task_id=task_id,
                    raw_submit_response=submit_data,
                    warnings=warnings,
                )

            final_status = str(task_data.get("status", "")).strip().upper()
            provider_status = str(task_data.get("provider_status", "")).strip()

            if final_status != "SUCCESS":
                return AssetAcquisitionResult(
                    success=False,
                    message=f"asset task finished with status={final_status}",
                    task_id=task_id,
                    provider_status=provider_status,
                    raw_submit_response=submit_data,
                    raw_task_response=task_data,
                    warnings=warnings,
                )

            asset = task_data.get("result_asset")
            if not isinstance(asset, dict) or not asset:
                return AssetAcquisitionResult(
                    success=False,
                    message="task SUCCESS but result_asset missing",
                    task_id=task_id,
                    provider_status=provider_status,
                    raw_submit_response=submit_data,
                    raw_task_response=task_data,
                    warnings=warnings,
                )

            download_url = str(asset.get("download_url", "")).strip()
            if not download_url:
                return AssetAcquisitionResult(
                    success=False,
                    message="task SUCCESS but result_asset.download_url missing",
                    task_id=task_id,
                    provider_status=provider_status,
                    asset_metadata=asset,
                    raw_submit_response=submit_data,
                    raw_task_response=task_data,
                    warnings=warnings,
                )

            local_path = download_dir / f"{Path(target_part).stem}_{uuid.uuid4().hex}.stl"
            try:
                saved = self._download_file(download_url, local_path)
            except Exception as exc:
                return AssetAcquisitionResult(
                    success=False,
                    message=f"download generated asset failed: {exc}",
                    task_id=task_id,
                    provider_status=provider_status,
                    download_url=download_url,
                    asset_metadata=asset,
                    raw_submit_response=submit_data,
                    raw_task_response=task_data,
                    warnings=warnings,
                )

            return AssetAcquisitionResult(
                success=True,
                message="generated asset downloaded",
                local_stl_path=saved,
                download_url=download_url,
                task_id=task_id,
                provider_status=provider_status,
                asset_metadata=asset,
                raw_submit_response=submit_data,
                raw_task_response=task_data,
                warnings=warnings,
            )

        if status in {"CANDIDATE_REVIEW_REQUIRED", "PROMPT_REVIEW_REQUIRED"}:
            return AssetAcquisitionResult(
                success=False,
                message=(
                    f"unsupported review status in current offline workflow: {status}. "
                    "Please enable auto approval/accept or force generate."
                ),
                raw_submit_response=submit_data,
                warnings=warnings,
            )

        return AssetAcquisitionResult(
            success=False,
            message=f"unsupported asset generate status: {status}",
            raw_submit_response=submit_data,
            warnings=warnings,
        )