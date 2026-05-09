from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    candidate_assets: list[Dict[str, Any]] | None = None

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

    def _coerce_asset_dict(self, item: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict) or not item:
            return None

        nested_asset = item.get("asset")
        if isinstance(nested_asset, dict) and nested_asset:
            return nested_asset

        if item.get("download_url"):
            return item

        return None

    def _extract_candidate_assets(self, data: Dict[str, Any], *, max_assets: int) -> List[Dict[str, Any]]:
        assets: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def add_asset(raw: Any) -> None:
            asset = self._coerce_asset_dict(raw)
            if not asset:
                return
            key = str(asset.get("download_url") or asset.get("id") or asset.get("asset_id") or asset)
            if key in seen:
                return
            seen.add(key)
            assets.append(asset)

        add_asset(data.get("selected_asset"))
        add_asset(data.get("result_asset"))

        for list_key in ["candidates", "result_assets", "assets"]:
            items = data.get(list_key) or []
            if isinstance(items, list):
                for item in items:
                    add_asset(item)
                    if len(assets) >= max_assets:
                        return assets[:max_assets]

        return assets[:max_assets]

    def _extract_selected_asset(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        assets = self._extract_candidate_assets(data, max_assets=1)
        return assets[0] if assets else None

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

    def _download_assets(
        self,
        *,
        target_part: str,
        assets: List[Dict[str, Any]],
        download_dir: Path,
        warnings: list[str],
        raw_submit_response: Dict[str, Any] | None = None,
        raw_task_response: Dict[str, Any] | None = None,
        task_id: str = "",
        provider_status: str = "",
        message: str,
    ) -> AssetAcquisitionResult:
        downloaded_assets: list[Dict[str, Any]] = []

        for idx, asset in enumerate(assets[:5], start=1):
            download_url = str(asset.get("download_url", "")).strip()
            if not download_url:
                warnings.append(f"candidate_asset_{idx}_missing_download_url")
                continue

            local_path = download_dir / f"{Path(target_part).stem}_candidate_{idx}_{uuid.uuid4().hex}.stl"
            try:
                saved = self._download_file(download_url, local_path)
            except Exception as exc:
                warnings.append(f"download_candidate_asset_{idx}_failed={exc}")
                continue

            downloaded_assets.append(
                {
                    "rank": idx,
                    "local_stl_path": saved,
                    "download_url": download_url,
                    "asset_metadata": asset,
                }
            )

        if not downloaded_assets:
            return AssetAcquisitionResult(
                success=False,
                message="no candidate asset could be downloaded",
                task_id=task_id,
                provider_status=provider_status,
                raw_submit_response=raw_submit_response,
                raw_task_response=raw_task_response,
                warnings=warnings,
                candidate_assets=[],
            )

        first = downloaded_assets[0]
        return AssetAcquisitionResult(
            success=True,
            message=message,
            local_stl_path=str(first["local_stl_path"]),
            download_url=str(first["download_url"]),
            task_id=task_id,
            provider_status=provider_status,
            asset_metadata=dict(first["asset_metadata"]),
            raw_submit_response=raw_submit_response,
            raw_task_response=raw_task_response,
            warnings=warnings,
            candidate_assets=downloaded_assets,
        )

    def acquire_asset_stl_candidates(
        self,
        *,
        target_part: str,
        asset_request: Dict[str, Any],
        download_dir: Path,
        max_assets: int = 5,
    ) -> AssetAcquisitionResult:
        asset_request = dict(asset_request)
        asset_request["topk"] = int(max_assets)

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
            "topk": asset_request.get("topk", max_assets),
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
            assets = self._extract_candidate_assets(submit_data, max_assets=max_assets)
            if not assets:
                return AssetAcquisitionResult(
                    success=False,
                    message="asset generate returned ASSET_SELECTED but no candidate asset found",
                    raw_submit_response=submit_data,
                    warnings=warnings,
                )
            return self._download_assets(
                target_part=target_part,
                assets=assets,
                download_dir=download_dir,
                warnings=warnings,
                raw_submit_response=submit_data,
                message=f"downloaded {min(len(assets), max_assets)} candidate asset(s)",
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

            assets = self._extract_candidate_assets(task_data, max_assets=max_assets)
            if not assets:
                return AssetAcquisitionResult(
                    success=False,
                    message="task SUCCESS but result asset missing",
                    task_id=task_id,
                    provider_status=provider_status,
                    raw_submit_response=submit_data,
                    raw_task_response=task_data,
                    warnings=warnings,
                )

            return self._download_assets(
                target_part=target_part,
                assets=assets,
                download_dir=download_dir,
                warnings=warnings,
                raw_submit_response=submit_data,
                raw_task_response=task_data,
                task_id=task_id,
                provider_status=provider_status,
                message=f"downloaded {min(len(assets), max_assets)} generated candidate asset(s)",
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

    def acquire_asset_stl(
        self,
        *,
        target_part: str,
        asset_request: Dict[str, Any],
        download_dir: Path,
    ) -> AssetAcquisitionResult:
        """Backward-compatible single-asset acquisition wrapper."""
        return self.acquire_asset_stl_candidates(
            target_part=target_part,
            asset_request=asset_request,
            download_dir=download_dir,
            max_assets=1,
        )
