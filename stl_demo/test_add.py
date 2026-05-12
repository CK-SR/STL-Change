from pathlib import Path
import json
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _project_path_from_env(env_name: str, default: Path) -> Path:
    raw_value = os.getenv(env_name)
    path = Path(raw_value) if raw_value else default
    return path if path.is_absolute() else PROJECT_ROOT / path


from app.services.add_fit_service import AddFitService
from app.services.geometry_anchor_service import GeometryAnchorService
from app.services.part_constraint_service import PartConstraintService
from app.services.part_constraints_loader import (
    load_part_constraints,
    build_part_to_file_map_from_constraints,
)

# ====== 可通过环境变量覆盖；默认基于当前 stl_demo 目录，便于项目迁移 ======
constraints_path = _project_path_from_env(
    "STL_PART_CONSTRAINTS_PATH",
    PROJECT_ROOT / "data" / "metadata" / "part_constraints.json",
)
parts_dir = _project_path_from_env("STL_PARTS_DIR", PROJECT_ROOT / "data" / "stl_parts")
asset_stl = _project_path_from_env("ADD_FIT_ASSET_STL", PROJECT_ROOT / "data" / "assets" / "new.stl")
attach_to = os.getenv("ADD_FIT_ATTACH_TO", "BJ0013")  # 改成约束文件中的父部件 part_id
output_path = _project_path_from_env(
    "ADD_FIT_OUTPUT_PATH",
    PROJECT_ROOT / "output" / "add_fit_tests" / "new_asset_fitted.stl",
)
# ============================================================

output_path.parent.mkdir(parents=True, exist_ok=True)

part_constraints = load_part_constraints(constraints_path)
part_to_file = build_part_to_file_map_from_constraints(part_constraints, parts_dir)

if attach_to not in part_to_file:
    raise RuntimeError(
        f"找不到父部件 STL: attach_to={attach_to}, "
        f"当前可用 key={sorted(part_to_file.keys())[:20]}"
    )

constraint_service = PartConstraintService(constraints_path)

fit_service = AddFitService(
    anchor_service=GeometryAnchorService(),
    constraint_service=constraint_service,
)

result = fit_service.fit_imported_asset(
    imported_stl_path=asset_stl,
    attach_to=attach_to,
    attach_to_path=part_to_file[attach_to],
    output_path=output_path,
    asset_metadata={
        "category": "roof",
        "mount_region": "top",
        "target_type": "test_asset",
    },
    mount_request={
        "mount_region": "top",
        "placement_scope": "single",
        "preferred_strategy": "top_cover",
    },
    fit_policy={
        "category": "roof",
        "mount_region": "top",
    },
    visual_fit={},
    post_transform_overrides={},
)

print("success:", result.success)
print("message:", result.message)
print("output_path:", result.output_path)
print("warnings:", json.dumps(result.warnings, ensure_ascii=False, indent=2))
print("fit_plan keys:", list(result.fit_plan.keys()))

if not result.success:
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    raise SystemExit(1)
