from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_app_to_path() -> None:
    app_root = _repo_root() / "stl_demo"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))


def _parse_args() -> argparse.Namespace:
    root = _repo_root()
    default_constraints = root / "stl_demo" / "data" / "metadata" / "part_constraints.json"
    default_parts_dir = root / "stl_demo" / "data" / "stl_parts"
    default_asset = root / "stl_demo" / "data" / "assets" / "new_asset.stl"
    default_output = root / "stl_demo" / "output" / "add_fit_tests" / "new_asset_fitted.stl"
    default_report = root / "stl_demo" / "output" / "add_fit_tests" / "new_asset_fitted_report.json"

    parser = argparse.ArgumentParser(
        description=(
            "Run the current add/top_cover local fitting pipeline for one imported STL "
            "and validate the fitted result geometry."
        )
    )
    parser.add_argument("--constraints-path", type=Path, default=default_constraints)
    parser.add_argument("--parts-dir", type=Path, default=default_parts_dir)
    parser.add_argument("--asset-stl", type=Path, default=default_asset)
    parser.add_argument("--attach-to", default="BJ0013", help="Existing parent part_id or file key")
    parser.add_argument("--output-path", type=Path, default=default_output)
    parser.add_argument("--report-path", type=Path, default=default_report)

    parser.add_argument("--category", default="roof")
    parser.add_argument("--mount-region", default="top")
    parser.add_argument("--target-type", default="test_asset")
    parser.add_argument("--placement-scope", default="single")
    parser.add_argument("--preferred-strategy", default="top_cover")
    parser.add_argument("--target-ratio", type=float, default=0.92)
    parser.add_argument("--clearance-mm", type=float, default=0.0)
    parser.add_argument("--preserve-aspect-ratio", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--allow-axis-stretch", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--allow-unlimited-upscale", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--post-translate-x", type=float, default=0.0)
    parser.add_argument("--post-translate-y", type=float, default=0.0)
    parser.add_argument("--post-translate-z", type=float, default=0.0)
    parser.add_argument("--post-rotate-axis", choices=["x", "y", "z"], default="z")
    parser.add_argument("--post-rotate-degrees", type=float, default=0.0)
    parser.add_argument("--post-stretch-delta-mm", type=float, default=0.0)

    parser.add_argument(
        "--enable-vision-pose-selection",
        action="store_true",
        help=(
            "Enable current vision-model pose selection. OPENAI_BASE_URL/OPENAI_API_KEY "
            "must point to a vision-capable OpenAI-compatible endpoint."
        ),
    )
    parser.add_argument("--vision-max-candidates", type=int, default=None)
    return parser.parse_args()


def _path_to_str(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _path_to_str(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_path_to_str(v) for v in value]
    return value


def _mesh_summary(path: Path) -> dict[str, Any]:
    mesh = trimesh.load_mesh(path, force="mesh")
    extents = np.asarray(mesh.extents, dtype=float)
    bounds = np.asarray(mesh.bounds, dtype=float)
    return {
        "path": str(path),
        "exists": path.exists(),
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "is_empty": bool(mesh.is_empty),
        "is_watertight": bool(mesh.is_watertight),
        "volume": float(mesh.volume) if np.isfinite(mesh.volume) else None,
        "area": float(mesh.area) if np.isfinite(mesh.area) else None,
        "extents": [float(x) for x in extents.tolist()],
        "bounds": [[float(x) for x in row] for row in bounds.tolist()],
    }


def _last_surface_report(fit_plan: dict[str, Any]) -> dict[str, Any]:
    reports = fit_plan.get("surface_reports") or []
    if not isinstance(reports, list) or not reports:
        return {}
    last = reports[-1]
    return last if isinstance(last, dict) else {}


def _validate_add_result(result: Any, output_path: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    checks: list[str] = []
    failures: list[str] = []
    details: dict[str, Any] = {}

    def require(name: str, condition: bool, detail: Any = None) -> None:
        checks.append(name)
        if not condition:
            failures.append(name)
        if detail is not None:
            details[name] = detail

    require("fit_result_success", bool(result.success), result.message)
    require("output_path_exists", output_path.exists(), str(output_path))

    if output_path.exists():
        try:
            summary = _mesh_summary(output_path)
            details["output_mesh_summary"] = summary
            require("output_mesh_not_empty", not summary["is_empty"])
            require("output_mesh_has_faces", summary["faces"] > 0, summary["faces"])
            require("output_mesh_has_vertices", summary["vertices"] > 0, summary["vertices"])
            require(
                "output_mesh_extents_positive",
                all(float(x) > 0.0 for x in summary["extents"]),
                summary["extents"],
            )
        except Exception as exc:
            require("output_mesh_readable", False, str(exc))
    else:
        require("output_mesh_readable", False, "output file is missing")

    fit_plan = result.fit_plan if isinstance(result.fit_plan, dict) else {}
    surface_plan = fit_plan.get("surface_plan") if isinstance(fit_plan.get("surface_plan"), dict) else {}
    mount_strategy = str(surface_plan.get("mount_strategy", ""))
    details["resolved_mount_strategy"] = mount_strategy
    require("mount_strategy_top_cover", mount_strategy == "top_cover", mount_strategy)

    surface_reports = fit_plan.get("surface_reports") or []
    require("surface_reports_present", isinstance(surface_reports, list) and len(surface_reports) > 0, len(surface_reports))

    last_report = _last_surface_report(fit_plan)
    selected = last_report.get("selected_pose_candidate") if isinstance(last_report.get("selected_pose_candidate"), dict) else {}
    validation = selected.get("surface_validation") if isinstance(selected.get("surface_validation"), dict) else {}
    support_settle = selected.get("support_settle") if isinstance(selected.get("support_settle"), dict) else {}
    pose_selection = last_report.get("pose_selection") if isinstance(last_report.get("pose_selection"), dict) else {}

    details["selected_candidate_id"] = pose_selection.get("selected_candidate_id")
    details["pose_selection_message"] = pose_selection.get("message")
    details["surface_validation"] = validation
    details["support_settle"] = support_settle

    require("selected_surface_validation_valid", bool(validation.get("valid", False)), validation)
    if support_settle:
        contact_regions = int(support_settle.get("contact_regions_final", 0) or 0)
        outside_ratio = float(support_settle.get("outside_footprint_ratio", 1.0) or 0.0)
        require("top_cover_contact_regions_at_least_2", contact_regions >= 2, contact_regions)
        require("top_cover_outside_footprint_ratio_lte_0_35", outside_ratio <= 0.35, outside_ratio)

    return checks, failures, details


def main() -> int:
    args = _parse_args()

    if args.enable_vision_pose_selection:
        os.environ["ADD_VISION_POSE_SELECTION_ENABLED"] = "true"
    if args.vision_max_candidates is not None:
        os.environ["ADD_VISION_POSE_MAX_CANDIDATES"] = str(args.vision_max_candidates)

    _add_app_to_path()

    from app.services.add_fit_service import AddFitService
    from app.services.geometry_anchor_service import GeometryAnchorService
    from app.services.part_constraint_service import PartConstraintService
    from app.services.part_constraints_loader import (
        build_part_to_file_map_from_constraints,
        load_part_constraints,
    )

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)

    if not args.constraints_path.exists():
        raise FileNotFoundError(f"constraints_path not found: {args.constraints_path}")
    if not args.parts_dir.exists():
        raise FileNotFoundError(f"parts_dir not found: {args.parts_dir}")
    if not args.asset_stl.exists():
        raise FileNotFoundError(f"asset_stl not found: {args.asset_stl}")

    part_constraints = load_part_constraints(args.constraints_path)
    part_to_file = build_part_to_file_map_from_constraints(part_constraints, args.parts_dir)
    for stl_path in args.parts_dir.glob("*.stl"):
        part_to_file.setdefault(stl_path.name, stl_path)

    if args.attach_to not in part_to_file:
        available = sorted(part_to_file.keys())[:40]
        raise RuntimeError(
            f"找不到父部件 STL: attach_to={args.attach_to}, 当前可用 key 前40项={available}"
        )

    constraint_service = PartConstraintService(args.constraints_path)
    fit_service = AddFitService(
        anchor_service=GeometryAnchorService(),
        constraint_service=constraint_service,
    )

    post_transform_overrides: dict[str, Any] = {}
    if any(abs(x) > 1e-9 for x in [args.post_translate_x, args.post_translate_y, args.post_translate_z]):
        post_transform_overrides["translate"] = {
            "x": args.post_translate_x,
            "y": args.post_translate_y,
            "z": args.post_translate_z,
        }
    if abs(args.post_rotate_degrees) > 1e-9:
        post_transform_overrides["rotate"] = {
            "axis": args.post_rotate_axis,
            "degrees": args.post_rotate_degrees,
        }
    if abs(args.post_stretch_delta_mm) > 1e-9:
        post_transform_overrides["stretch"] = {"delta_mm": args.post_stretch_delta_mm}

    asset_metadata = {
        "category": args.category,
        "mount_region": args.mount_region,
        "placement_scope": args.placement_scope,
        "preferred_strategy": args.preferred_strategy,
        "target_type": args.target_type,
    }
    mount_request = {
        "mount_region": args.mount_region,
        "placement_scope": args.placement_scope,
        "preferred_strategy": args.preferred_strategy,
    }
    fit_policy = {
        "category": args.category,
        "mount_region": args.mount_region,
        "placement_scope": args.placement_scope,
        "preferred_strategy": args.preferred_strategy,
        "coverage_ratio": args.target_ratio,
        "clearance_mm": args.clearance_mm,
        "allow_stretch": args.allow_axis_stretch,
    }
    visual_fit = {
        "target_ratio": args.target_ratio,
        "preserve_aspect_ratio": args.preserve_aspect_ratio,
        "allow_axis_stretch": args.allow_axis_stretch,
        "allow_unlimited_upscale": args.allow_unlimited_upscale,
    }

    print("=== add fit test input ===")
    print("constraints_path:", args.constraints_path)
    print("parts_dir:", args.parts_dir)
    print("asset_stl:", args.asset_stl)
    print("attach_to:", args.attach_to, "=>", part_to_file[args.attach_to])
    print("output_path:", args.output_path)
    print("mount_request:", json.dumps(mount_request, ensure_ascii=False))
    print("visual_fit:", json.dumps(visual_fit, ensure_ascii=False))

    result = fit_service.fit_imported_asset(
        imported_stl_path=args.asset_stl,
        attach_to=args.attach_to,
        attach_to_path=part_to_file[args.attach_to],
        output_path=args.output_path,
        asset_metadata=asset_metadata,
        mount_request=mount_request,
        fit_policy=fit_policy,
        visual_fit=visual_fit,
        post_transform_overrides=post_transform_overrides,
    )

    checks, failures, details = _validate_add_result(result, args.output_path)
    report = {
        "input": {
            "constraints_path": args.constraints_path,
            "parts_dir": args.parts_dir,
            "asset_stl": args.asset_stl,
            "attach_to": args.attach_to,
            "attach_to_path": part_to_file[args.attach_to],
            "output_path": args.output_path,
            "asset_metadata": asset_metadata,
            "mount_request": mount_request,
            "fit_policy": fit_policy,
            "visual_fit": visual_fit,
            "post_transform_overrides": post_transform_overrides,
        },
        "result": result.to_dict(),
        "checks": checks,
        "failures": failures,
        "details": details,
    }
    args.report_path.write_text(json.dumps(_path_to_str(report), ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== add fit result ===")
    print("success:", result.success)
    print("message:", result.message)
    print("output_path:", result.output_path)
    print("warnings:", json.dumps(result.warnings, ensure_ascii=False, indent=2))
    print("selected_candidate_id:", details.get("selected_candidate_id"))
    print("pose_selection_message:", details.get("pose_selection_message"))
    print("checks:", len(checks))
    print("failures:", json.dumps(failures, ensure_ascii=False, indent=2))
    print("report_path:", args.report_path)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
