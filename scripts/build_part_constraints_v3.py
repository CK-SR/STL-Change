# -*- coding: utf-8 -*-
"""
增强版：通用化 part_constraints.json 生成脚本（弱化表格父件，强化候选集 + LLM 受约束判定）

核心目标：
1. 汇总 2.1 / 3.1 / 3.2 / 4.1 / 4.3
2. 读取 STL，提取稳定几何字段
3. 识别虚拟父部件 / 实体部件
4. 生成 parts_master_table
5. 生成 part_constraints.json
6. 使用“几何候选集 + LLM受约束选择”推断 attachment/follow 关系
7. 表格父部件仅作为 declared_parent 弱提示，不作为联动真值

依赖：
pip install pandas numpy trimesh openai

可选：
pip install mapbox-earcut rtree
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import hashlib
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import trimesh


# =========================
# 配置区
# =========================
CSV_DIR = Path(r"D:\bica\k-8\AAV7A1\csv")
STL_ROOT = Path(r"D:\bica\k-8\AAV7A1\model")
OUT_DIR = Path(r"D:\bica\k-8\AAV7A1\output")

TARGET_BASIC_CSV = CSV_DIR / "2.1目标基本信息数据.csv"
PHYSICAL_CSV = CSV_DIR / "3.1目标物理结构数据.csv"
MODEL_CSV = CSV_DIR / "3.2目标三维模型数据.csv"
FUNCTION_CSV = CSV_DIR / "4.1目标功能结构数据.csv"
FUNC_PART_MAP_CSV = CSV_DIR / "4.3目标功能与部件映射数据.csv"

MASTER_CSV = OUT_DIR / "parts_master_table_v4.csv"
MASTER_JSON = OUT_DIR / "parts_master_table_v4.json"
CONSTRAINTS_JSON = OUT_DIR / "part_constraints.json"
LLM_CACHE_FILE = OUT_DIR / "llm_cache_v4.json"

ENABLE_LLM = True
LLM_SCOPE = "real_only"

LLM_TIMEOUT_SEC = 60
LLM_MAX_RETRIES = 2
LLM_SLEEP_BETWEEN_CALLS_SEC = 0.8

API_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL_NAME = os.getenv("LLM_MODEL", "qwen3.5-122b-a10b")

# 邻接关系阈值（AABB gap）
NEIGHBOR_GAP_MM = 10.0

# 联动候选父件筛选阈值
ATTACHMENT_CANDIDATE_TOPK = 6
ATTACHMENT_MIN_SCORE = 18.0

# fallback 建链阈值
FALLBACK_LINK_SCORE = 48.0
FALLBACK_SIZE_RATIO = 1.8

DEFAULT_CLEARANCE_MIN_MM = 2.0

ALLOWED_OP_ENUM = {
    "view",
    "select",
    "hide",
    "measure",
    "translate",
    "rotate",
    "stretch",
    "add_attach",
    "delete",
    "modify_geometry",
    "no_direct_edit",
}

EXTRA_FORBIDDEN_ENUM = {
    "uniform_scale",
    "delete_core",
}


# =========================
# 通用工具
# =========================
def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_str(x: Any) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def safe_float(x: Any) -> Optional[float]:
    try:
        if pd.isna(x) or str(x).strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def round_or_none(x: Any, ndigits: int = 6) -> Optional[float]:
    try:
        if x is None:
            return None
        return round(float(x), ndigits)
    except Exception:
        return None


def json_default(obj: Any):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not serializable: {type(obj)}")


def read_csv_auto(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "gbk", "gb18030", "utf-8"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"读取失败: {path}\n{last_err}")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_op_token(token: str) -> Optional[str]:
    t = safe_str(token).lower()
    if not t:
        return None

    mapping = {
        "查看": "view",
        "浏览": "view",
        "view": "view",

        "选择": "select",
        "select": "select",

        "隐藏": "hide",
        "hide": "hide",

        "测量": "measure",
        "measure": "measure",

        "平移": "translate",
        "translate": "translate",

        "旋转": "rotate",
        "rotate": "rotate",

        "拉伸": "stretch",
        "伸缩": "stretch",
        "沿主轴伸长": "stretch",
        "stretch": "stretch",

        "添加附件": "add_attach",
        "挂载附件": "add_attach",
        "attach": "add_attach",
        "add_attach": "add_attach",

        "删除": "delete",
        "delete": "delete",

        "修改网格几何": "modify_geometry",
        "修改几何": "modify_geometry",
        "modify_geometry": "modify_geometry",

        "不允许直接编辑": "no_direct_edit",
        "no_direct_edit": "no_direct_edit",

        "uniform_scale": "uniform_scale",
        "整体缩放": "uniform_scale",

        "删除核心结构": "delete_core",
        "delete_core": "delete_core",
    }

    if t in mapping:
        return mapping[t]

    return t if t in ALLOWED_OP_ENUM or t in EXTRA_FORBIDDEN_ENUM else None


def normalize_op_list(values: Any) -> List[str]:
    items: List[str] = []
    if isinstance(values, list):
        raw_items = values
    else:
        raw = safe_str(values)
        if not raw:
            return []
        raw_items = re.split(r"[,，/、;\s]+", raw)

    for x in raw_items:
        norm = normalize_op_token(str(x))
        if norm:
            items.append(norm)

    seen = set()
    result = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


# =========================
# 几何提取
# =========================
def extract_stl_features(stl_path: Path) -> Dict[str, Any]:
    result = {
        "stl_abs_path": str(stl_path),
        "has_stl_file": int(stl_path.exists()),
        "mesh_loaded": 0,
        "geometry_error": "",

        "最小x": None,
        "最小y": None,
        "最小z": None,
        "最大x": None,
        "最大y": None,
        "最大z": None,

        "长度(mm)": None,
        "宽度(mm)": None,
        "高度(mm)": None,

        "几何中心x(mm)": None,
        "几何中心y(mm)": None,
        "几何中心z(mm)": None,

        "质心x": None,
        "质心y": None,
        "质心z": None,

        "OBB长度": None,
        "OBB宽度": None,
        "OBB高度": None,

        "主方向轴X": "",
        "主方向轴Y": "",
        "主方向轴Z": "",

        "顶点数": None,
        "三角面数": None,
        "是否封闭模型": None,
        "Euler数": None,
        "包围盒体积估计": None,
        "尺寸是否合法": None,
        "是否通过验证": None,
    }

    if not stl_path.exists():
        return result

    try:
        mesh = trimesh.load_mesh(stl_path, process=False)

        if mesh is None:
            result["geometry_error"] = "mesh is None"
            return result

        if isinstance(mesh, trimesh.Scene):
            if len(mesh.geometry) == 0:
                result["geometry_error"] = "scene has no geometry"
                return result
            mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

        if len(mesh.vertices) == 0:
            result["geometry_error"] = "mesh has no vertices"
            return result

        result["mesh_loaded"] = 1
        result["顶点数"] = int(len(mesh.vertices))
        result["三角面数"] = int(len(mesh.faces))

        bounds = mesh.bounds
        min_bound = bounds[0]
        max_bound = bounds[1]
        extents = max_bound - min_bound
        bbox_center = (min_bound + max_bound) / 2.0

        result["最小x"] = round_or_none(min_bound[0], 6)
        result["最小y"] = round_or_none(min_bound[1], 6)
        result["最小z"] = round_or_none(min_bound[2], 6)
        result["最大x"] = round_or_none(max_bound[0], 6)
        result["最大y"] = round_or_none(max_bound[1], 6)
        result["最大z"] = round_or_none(max_bound[2], 6)

        result["长度(mm)"] = round_or_none(extents[0], 6)
        result["宽度(mm)"] = round_or_none(extents[1], 6)
        result["高度(mm)"] = round_or_none(extents[2], 6)

        result["几何中心x(mm)"] = round_or_none(bbox_center[0], 6)
        result["几何中心y(mm)"] = round_or_none(bbox_center[1], 6)
        result["几何中心z(mm)"] = round_or_none(bbox_center[2], 6)

        try:
            cm = mesh.center_mass
            result["质心x"] = round_or_none(cm[0], 6)
            result["质心y"] = round_or_none(cm[1], 6)
            result["质心z"] = round_or_none(cm[2], 6)
        except Exception:
            pass

        try:
            obb = mesh.bounding_box_oriented
            obb_extents = obb.primitive.extents
            obb_transform = obb.primitive.transform
            main_axes = obb_transform[:3, :3]

            result["OBB长度"] = round_or_none(obb_extents[0], 6)
            result["OBB宽度"] = round_or_none(obb_extents[1], 6)
            result["OBB高度"] = round_or_none(obb_extents[2], 6)

            result["主方向轴X"] = json.dumps(
                [round(float(v), 6) for v in main_axes[:, 0].tolist()],
                ensure_ascii=False
            )
            result["主方向轴Y"] = json.dumps(
                [round(float(v), 6) for v in main_axes[:, 1].tolist()],
                ensure_ascii=False
            )
            result["主方向轴Z"] = json.dumps(
                [round(float(v), 6) for v in main_axes[:, 2].tolist()],
                ensure_ascii=False
            )
        except Exception:
            pass

        try:
            result["是否封闭模型"] = int(bool(mesh.is_watertight))
        except Exception:
            result["是否封闭模型"] = None

        try:
            result["Euler数"] = int(mesh.euler_number)
        except Exception:
            result["Euler数"] = None

        try:
            result["包围盒体积估计"] = round_or_none(extents[0] * extents[1] * extents[2], 6)
        except Exception:
            pass

        size_ok = False
        try:
            size_ok = bool(np.all(extents >= 0) and np.any(extents > 0))
        except Exception:
            size_ok = False

        result["尺寸是否合法"] = int(size_ok)
        result["是否通过验证"] = int(
            result["mesh_loaded"] == 1
            and result["尺寸是否合法"] == 1
            and (result["顶点数"] or 0) > 0
            and (result["三角面数"] or 0) > 0
        )

        return result

    except Exception as e:
        result["geometry_error"] = f"{type(e).__name__}: {e}"
        return result


# =========================
# 几何/关系辅助
# =========================
def parse_axis(axis_json: str) -> Optional[List[float]]:
    try:
        arr = json.loads(axis_json)
        if isinstance(arr, list) and len(arr) == 3:
            return [float(arr[0]), float(arr[1]), float(arr[2])]
    except Exception:
        return None
    return None


def choose_primary_axis(row: Dict[str, Any]) -> List[float]:
    axis_x = parse_axis(safe_str(row.get("主方向轴X", "")))
    if axis_x:
        norm = math.sqrt(sum(v * v for v in axis_x))
        if norm > 1e-9:
            return [round(v / norm, 6) for v in axis_x]

    lx = safe_float(row.get("长度(mm)")) or 0.0
    ly = safe_float(row.get("宽度(mm)")) or 0.0
    lz = safe_float(row.get("高度(mm)")) or 0.0

    dims = [lx, ly, lz]
    idx = int(np.argmax(dims))
    if idx == 0:
        return [1.0, 0.0, 0.0]
    if idx == 1:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


def infer_anchor_mode(row: Dict[str, Any], semantic_role: str = "") -> str:
    if int(row.get("is_virtual_part", 0)) == 1:
        return "none"

    if semantic_role == "mounted_accessory":
        return "parent_attach"

    aabb = [
        safe_float(row.get("长度(mm)")) or 0.0,
        safe_float(row.get("宽度(mm)")) or 0.0,
        safe_float(row.get("高度(mm)")) or 0.0,
    ]
    max_dim = max(aabb) if aabb else 0.0
    min_dim = min(aabb) if aabb else 0.0

    if max_dim > 0 and min_dim > 0 and max_dim / max(min_dim, 1e-6) > 3.0:
        return "base_face_fixed"

    return "center"


def infer_edit_type(row: Dict[str, Any]) -> str:
    if int(row.get("is_virtual_part", 0)) == 1:
        return "virtual_assembly"

    part_name = safe_str(row.get("部件名称"))
    function_names = safe_str(row.get("mapped_function_names"))
    text = f"{part_name} {function_names}"

    if any(k in text for k in ["装甲", "结构", "框架", "支撑", "壳体", "蒙皮", "承力"]):
        return "structural_part"
    if any(k in text for k in ["门", "窗", "盖", "舱", "面板"]):
        return "panel_part"
    if any(k in text for k in ["履带", "轮", "传动", "动力", "发动机", "推进", "泵", "齿轮"]):
        return "mechanical_part"
    if any(k in text for k in ["观察", "瞄准", "传感", "光学", "通信", "火控", "武器", "设备"]):
        return "device_part"

    return "general_part"


def infer_default_ops(edit_type: str, is_virtual_part: int) -> Tuple[List[str], List[str]]:
    if is_virtual_part:
        return (
            ["view", "select", "hide"],
            ["translate", "rotate", "stretch", "add_attach", "delete", "modify_geometry", "uniform_scale", "delete_core"],
        )

    if edit_type == "structural_part":
        return (
            ["view", "select", "hide", "measure", "translate", "rotate", "stretch"],
            ["uniform_scale", "delete_core"],
        )
    if edit_type == "panel_part":
        return (
            ["view", "select", "hide", "measure", "translate", "rotate", "modify_geometry"],
            ["uniform_scale", "delete_core"],
        )
    if edit_type == "mechanical_part":
        return (
            ["view", "select", "hide", "measure", "translate", "rotate"],
            ["stretch", "uniform_scale", "delete_core"],
        )
    if edit_type == "device_part":
        return (
            ["view", "select", "hide", "measure", "translate", "rotate", "add_attach"],
            ["stretch", "uniform_scale", "delete_core"],
        )

    return (
        ["view", "select", "hide", "measure", "translate", "rotate"],
        ["uniform_scale"],
    )


def bbox_gap_mm(row_a: Dict[str, Any], row_b: Dict[str, Any]) -> Optional[float]:
    try:
        a_min = np.array([
            float(row_a["最小x"]),
            float(row_a["最小y"]),
            float(row_a["最小z"]),
        ])
        a_max = np.array([
            float(row_a["最大x"]),
            float(row_a["最大y"]),
            float(row_a["最大z"]),
        ])
        b_min = np.array([
            float(row_b["最小x"]),
            float(row_b["最小y"]),
            float(row_b["最小z"]),
        ])
        b_max = np.array([
            float(row_b["最大x"]),
            float(row_b["最大y"]),
            float(row_b["最大z"]),
        ])
    except Exception:
        return None

    dx = max(0.0, max(b_min[0] - a_max[0], a_min[0] - b_max[0]))
    dy = max(0.0, max(b_min[1] - a_max[1], a_min[1] - b_max[1]))
    dz = max(0.0, max(b_min[2] - a_max[2], a_min[2] - b_max[2]))

    return round(float(math.sqrt(dx * dx + dy * dy + dz * dz)), 6)


def center_distance(row_a: Dict[str, Any], row_b: Dict[str, Any]) -> Optional[float]:
    try:
        a = np.array([
            float(row_a["几何中心x(mm)"]),
            float(row_a["几何中心y(mm)"]),
            float(row_a["几何中心z(mm)"]),
        ])
        b = np.array([
            float(row_b["几何中心x(mm)"]),
            float(row_b["几何中心y(mm)"]),
            float(row_b["几何中心z(mm)"]),
        ])
        return float(np.linalg.norm(a - b))
    except Exception:
        return None


def part_diag_length(row: Dict[str, Any]) -> float:
    lx = safe_float(row.get("长度(mm)")) or 0.0
    ly = safe_float(row.get("宽度(mm)")) or 0.0
    lz = safe_float(row.get("高度(mm)")) or 0.0
    return float(math.sqrt(lx * lx + ly * ly + lz * lz))


def build_neighbors(records: List[Dict[str, Any]], target_id: str) -> Dict[str, List[str]]:
    same_target = [r for r in records if safe_str(r.get("目标ID")) == target_id and int(r.get("has_stl_file", 0)) == 1]
    result: Dict[str, List[str]] = {safe_str(r["部件ID"]): [] for r in same_target}

    for i in range(len(same_target)):
        for j in range(i + 1, len(same_target)):
            a = same_target[i]
            b = same_target[j]
            gap = bbox_gap_mm(a, b)
            if gap is None:
                continue
            if gap <= NEIGHBOR_GAP_MM:
                result[safe_str(a["部件ID"])].append(safe_str(b["部件ID"]))
                result[safe_str(b["部件ID"])].append(safe_str(a["部件ID"]))
    return result


def infer_symmetry_group(row: Dict[str, Any]) -> str:
    name = safe_str(row.get("部件名称"))
    if not name:
        return ""
    if "左" in name:
        return name.replace("左", "{LR}")
    if "右" in name:
        return name.replace("右", "{LR}")
    return ""


# =========================
# 业务映射
# =========================
def build_children_map(physical_df: pd.DataFrame) -> Dict[str, List[str]]:
    children_map: Dict[str, List[str]] = {}
    for _, row in physical_df.iterrows():
        part_id = safe_str(row.get("部件ID", ""))
        parent_id = safe_str(row.get("父部件ID", ""))
        if parent_id:
            children_map.setdefault(parent_id, []).append(part_id)
    return children_map


def build_name_map(physical_df: pd.DataFrame) -> Dict[str, str]:
    result = {}
    for _, row in physical_df.iterrows():
        pid = safe_str(row.get("部件ID", ""))
        pname = safe_str(row.get("部件名称", ""))
        if pid:
            result[pid] = pname
    return result


def build_function_maps(function_df: pd.DataFrame, func_part_df: pd.DataFrame) -> Dict[str, Dict[str, List[str]]]:
    func_name_map = {}
    for _, row in function_df.iterrows():
        fid = safe_str(row.get("功能ID", ""))
        fname = safe_str(row.get("功能名称", ""))
        if fid:
            func_name_map[fid] = fname

    part_func_map: Dict[str, Dict[str, List[str]]] = {}
    for _, row in func_part_df.iterrows():
        pid = safe_str(row.get("部件ID", ""))
        fid = safe_str(row.get("功能ID", ""))
        if not pid:
            continue
        part_func_map.setdefault(pid, {"ids": [], "names": []})
        if fid:
            part_func_map[pid]["ids"].append(fid)
            if func_name_map.get(fid):
                part_func_map[pid]["names"].append(func_name_map[fid])

    for pid, item in part_func_map.items():
        item["ids"] = sorted(list({x for x in item["ids"] if x}))
        item["names"] = sorted(list({x for x in item["names"] if x}))
    return part_func_map


# =========================
# 通用 attachment 候选评分
# =========================
def generic_attachment_score(
    child: Dict[str, Any],
    parent: Dict[str, Any],
    is_neighbor: bool,
) -> float:
    child_diag = part_diag_length(child)
    parent_diag = part_diag_length(parent)
    gap = bbox_gap_mm(child, parent)
    dist = center_distance(child, parent)

    score = 0.0

    if parent_diag > child_diag > 0:
        ratio = parent_diag / max(child_diag, 1e-6)
        if 1.5 <= ratio <= 20:
            score += 30.0
        elif ratio > 1.0:
            score += 15.0

    if is_neighbor:
        score += 25.0

    if gap is not None:
        score += max(0.0, 15.0 - min(gap, 15.0))

    if dist is not None:
        denom = max(parent_diag + child_diag, 1e-6)
        score += max(0.0, 18.0 - min((dist / denom) * 10.0, 18.0))

    if int(parent.get("has_stl_file", 0)) == 1 and int(parent.get("is_virtual_part", 0)) == 0:
        score += 8.0

    parent_edit_type = safe_str(parent.get("edit_type"))
    if parent_edit_type in {"structural_part", "device_part", "general_part"}:
        score += 4.0

    child_functions = set(x for x in safe_str(child.get("mapped_function_names")).split(",") if x)
    parent_functions = set(x for x in safe_str(parent.get("mapped_function_names")).split(",") if x)
    if child_functions and parent_functions and child_functions.intersection(parent_functions):
        score += 6.0

    return score


# =========================
# LLM 助手
# =========================
class LLMHelper:
    def __init__(self, enabled: bool, cache_path: Path):
        self.enabled = enabled and bool(API_KEY)
        self.cache_path = cache_path
        self.cache = load_cache(cache_path)
        self.client = None
        if self.enabled:
            from openai import OpenAI
            self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    def should_call(self, row: Dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if LLM_SCOPE == "all":
            return True
        if LLM_SCOPE == "real_only":
            return int(row.get("has_stl_file", 0)) == 1
        return False

    def infer_constraint_fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = {
            "llm_called": 0,
            "llm_cache_hit": 0,
            "llm_success": 0,
            "llm_response_source": "",
            "llm_error": "",
        }

        if not self.enabled:
            status["llm_response_source"] = "disabled"
            return status

        prompt_data = json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)
        key = sha1_text("constraint_fields_v4:" + prompt_data)

        if key in self.cache:
            data = dict(self.cache[key])
            data.update({
                "llm_called": 0,
                "llm_cache_hit": 1,
                "llm_success": 1,
                "llm_response_source": "cache",
                "llm_error": "",
            })
            return data

        system_prompt = """
你是一名面向 STL 装备模型编辑的轻量约束补全助手。
请基于目标信息、部件信息、层级、功能映射、STL几何摘要，补全部件约束字段。

严格要求：
1. 只能输出 JSON 对象。
2. allowed_ops 和 forbidden_ops 只能从以下英文枚举中选择：
   view, select, hide, measure, translate, rotate, stretch, add_attach, delete, modify_geometry, no_direct_edit, uniform_scale, delete_core
3. anchor_mode 只能取：
   base_face_fixed, center, axis_fixed, parent_attach, none
4. edit_type 只能取：
   structural_part, panel_part, mechanical_part, device_part, virtual_assembly, general_part
5. semantic_role 只能取：
   base_component, mounted_accessory, cover_panel, drive_component, sensor_component, weapon_component, general_component, virtual_assembly
6. 不要臆造不存在的部件关系。
7. 原始 declared_parent 只是弱提示，不等于联动父件。

输出格式：
{
  "edit_type": "...",
  "anchor_mode": "...",
  "allowed_ops": ["..."],
  "forbidden_ops": ["..."],
  "clearance_min_mm": 2.0,
  "semantic_note": "...",
  "semantic_role": "..."
}
""".strip()

        user_prompt = f"请基于以下数据补全部件约束：\n{prompt_data}"

        last_err = ""
        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                status["llm_called"] = 1
                status["llm_response_source"] = "api"

                resp = self.client.chat.completions.create(
                    model=MODEL_NAME,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout=LLM_TIMEOUT_SEC,
                )

                text = resp.choices[0].message.content.strip()
                data = json.loads(text)
                data["allowed_ops"] = normalize_op_list(data.get("allowed_ops", []))
                data["forbidden_ops"] = normalize_op_list(data.get("forbidden_ops", []))

                status["llm_success"] = 1
                data.update(status)

                self.cache[key] = data
                save_cache(self.cache_path, self.cache)
                time.sleep(LLM_SLEEP_BETWEEN_CALLS_SEC)
                return data

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < LLM_MAX_RETRIES:
                    time.sleep(2 + attempt * 2)
                    continue

        status["llm_called"] = 1
        status["llm_success"] = 0
        status["llm_response_source"] = "api"
        status["llm_error"] = last_err
        return status

    def infer_attachment_link(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = {
            "link_llm_called": 0,
            "link_llm_cache_hit": 0,
            "link_llm_success": 0,
            "link_llm_response_source": "",
            "link_llm_error": "",
        }

        if not self.enabled:
            status["link_llm_response_source"] = "disabled"
            return status

        prompt_data = json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)
        key = sha1_text("attachment_link_v4:" + prompt_data)

        if key in self.cache:
            data = dict(self.cache[key])
            data.update({
                "link_llm_called": 0,
                "link_llm_cache_hit": 1,
                "link_llm_success": 1,
                "link_llm_response_source": "cache",
                "link_llm_error": "",
            })
            return data

        system_prompt = """
你是一名装配联动关系判定助手。
任务：在给定的候选父件集合中，判断当前部件是否应作为 mounted accessory 跟随某个父件做 rigid follow 变换。

严格要求：
1. 只能从候选父件列表中选择 attachment_parent_part_id，不能输出候选列表外 part_id。
2. 如果不应建立联动关系，attachment_parent_part_id 必须输出空字符串。
3. follow_ops 只能是 []、["translate"]、["rotate"]、["translate","rotate"] 之一。
4. link_type 只能输出 "" 或 "rigid_follow"。
5. 原始 declared_parent 只是弱提示，不是必须选择项。
6. 只有当你有较高把握当前部件是安装在某个更大父件上的附属件时，才输出 rigid_follow。

输出格式：
{
  "attachment_parent_part_id": "",
  "follow_ops": [],
  "link_type": "",
  "confidence": 0.0
}
""".strip()

        user_prompt = f"请判断以下部件是否应建立联动挂载关系：\n{prompt_data}"

        last_err = ""
        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                status["link_llm_called"] = 1
                status["link_llm_response_source"] = "api"

                resp = self.client.chat.completions.create(
                    model=MODEL_NAME,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout=LLM_TIMEOUT_SEC,
                )

                text = resp.choices[0].message.content.strip()
                data = json.loads(text)
                data["follow_ops"] = normalize_op_list(data.get("follow_ops", []))

                status["link_llm_success"] = 1
                data.update(status)

                self.cache[key] = data
                save_cache(self.cache_path, self.cache)
                time.sleep(LLM_SLEEP_BETWEEN_CALLS_SEC)
                return data

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < LLM_MAX_RETRIES:
                    time.sleep(2 + attempt * 2)
                    continue

        status["link_llm_called"] = 1
        status["link_llm_success"] = 0
        status["link_llm_response_source"] = "api"
        status["link_llm_error"] = last_err
        return status


# =========================
# 联动关系推断
# =========================
def infer_attachment_links(
    records: List[Dict[str, Any]],
    neighbors_map: Dict[str, List[str]],
    llm: LLMHelper,
) -> Dict[str, Dict[str, Any]]:
    row_by_id = {safe_str(r.get("部件ID")): r for r in records if safe_str(r.get("部件ID"))}
    result: Dict[str, Dict[str, Any]] = {}

    for child in records:
        child_id = safe_str(child.get("部件ID"))
        if not child_id:
            continue
        if int(child.get("has_stl_file", 0)) != 1 or int(child.get("is_virtual_part", 0)) == 1:
            continue

        child_diag = part_diag_length(child)
        if child_diag <= 0:
            continue

        target_id = safe_str(child.get("目标ID"))
        declared_parent_id = safe_str(child.get("父部件ID"))
        declared_parent_name = safe_str(child.get("父部件名称"))
        child_neighbors = set(neighbors_map.get(child_id, []))

        candidates: List[Dict[str, Any]] = []

        for parent in records:
            parent_id = safe_str(parent.get("部件ID"))
            if not parent_id or parent_id == child_id:
                continue
            if safe_str(parent.get("目标ID")) != target_id:
                continue
            if int(parent.get("has_stl_file", 0)) != 1 or int(parent.get("is_virtual_part", 0)) == 1:
                continue

            parent_diag = part_diag_length(parent)
            if parent_diag <= child_diag:
                continue

            gap = bbox_gap_mm(child, parent)
            dist = center_distance(child, parent)
            is_neighbor = parent_id in child_neighbors

            score = generic_attachment_score(child, parent, is_neighbor=is_neighbor)

            # 把 declared_parent 只作为弱提示
            if declared_parent_id and parent_id == declared_parent_id:
                score += 3.0

            if gap is not None and gap > 120:
                score -= 18.0
            if dist is not None and dist > (parent_diag + child_diag) * 2.5:
                score -= 18.0

            if score < ATTACHMENT_MIN_SCORE:
                continue

            candidates.append({
                "part_id": parent_id,
                "part_name": safe_str(parent.get("部件名称")),
                "score": round(score, 3),
                "gap_mm": gap,
                "center_distance_mm": dist,
                "diag_mm": round(parent_diag, 3),
                "is_neighbor": is_neighbor,
                "declared_parent_match": bool(declared_parent_id and parent_id == declared_parent_id),
                "edit_type": safe_str(parent.get("edit_type")),
                "semantic_role": safe_str(parent.get("semantic_role")),
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = candidates[:ATTACHMENT_CANDIDATE_TOPK]

        if not candidates:
            continue

        chosen_parent_id = ""
        chosen_follow_ops: List[str] = []
        chosen_link_type = ""
        chosen_confidence = 0.0
        chosen_source = ""

        if llm.should_call(child):
            payload = {
                "current_part": {
                    "part_id": child_id,
                    "part_name": safe_str(child.get("部件名称")),
                    "declared_parent_part_id": declared_parent_id,
                    "declared_parent_part_name": declared_parent_name,
                    "mapped_function_names": safe_str(child.get("mapped_function_names")),
                    "semantic_role": safe_str(child.get("semantic_role")),
                    "bbox_center": [
                        child.get("几何中心x(mm)"),
                        child.get("几何中心y(mm)"),
                        child.get("几何中心z(mm)"),
                    ],
                    "aabb_extents": [
                        child.get("长度(mm)"),
                        child.get("宽度(mm)"),
                        child.get("高度(mm)"),
                    ],
                },
                "candidate_parents": candidates,
                "instruction": "请在候选集合中选择最合理的联动父件；若不应建链则输出空字符串。",
            }
            link_llm = llm.infer_attachment_link(payload)
            chosen_parent_id = safe_str(link_llm.get("attachment_parent_part_id"))
            chosen_follow_ops = normalize_op_list(link_llm.get("follow_ops", []))
            chosen_link_type = safe_str(link_llm.get("link_type"))
            chosen_confidence = float(link_llm.get("confidence", 0.0) or 0.0)

            valid_ids = {x["part_id"] for x in candidates}
            if chosen_parent_id not in valid_ids:
                chosen_parent_id = ""
                chosen_follow_ops = []
                chosen_link_type = ""
                chosen_confidence = 0.0
            else:
                chosen_source = "llm_candidate_selection"

        # fallback：只在得分足够高、尺寸比明显时保守建链
        if not chosen_parent_id:
            best = candidates[0]
            best_parent = row_by_id[best["part_id"]]
            ratio = part_diag_length(best_parent) / max(child_diag, 1e-6)

            if best["score"] >= FALLBACK_LINK_SCORE and ratio >= FALLBACK_SIZE_RATIO:
                chosen_parent_id = best["part_id"]
                chosen_follow_ops = ["translate", "rotate"]
                chosen_link_type = "rigid_follow"
                chosen_confidence = min(0.75, best["score"] / 100.0)
                chosen_source = "heuristic_fallback"

        if not chosen_parent_id:
            continue

        chosen_parent = row_by_id.get(chosen_parent_id)
        result[child_id] = {
            "attachment_parent_part_id": chosen_parent_id,
            "attachment_parent_part_name": safe_str(chosen_parent.get("部件名称")) if chosen_parent else "",
            "link_type": chosen_link_type or "rigid_follow",
            "follow_transform_of": chosen_parent_id,
            "follow_ops": chosen_follow_ops or ["translate", "rotate"],
            "link_source": chosen_source or "heuristic_fallback",
            "link_confidence": round(float(chosen_confidence), 4),
            "attachment_parent_candidates": candidates,
        }

    return result


def build_linked_children_map(
    attachment_links: Dict[str, Dict[str, Any]],
    row_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, List[str]]]:
    result: Dict[str, Dict[str, List[str]]] = {}

    for child_id, link in attachment_links.items():
        parent_id = safe_str(link.get("attachment_parent_part_id"))
        if not parent_id:
            continue

        child_name = ""
        child_row = row_by_id.get(child_id)
        if child_row:
            child_name = safe_str(child_row.get("部件名称"))

        result.setdefault(parent_id, {"ids": [], "names": []})
        result[parent_id]["ids"].append(child_id)
        if child_name:
            result[parent_id]["names"].append(child_name)

    for parent_id, item in result.items():
        item["ids"] = sorted(list(dict.fromkeys(item["ids"])))
        item["names"] = sorted(list(dict.fromkeys(item["names"])))

    return result


# =========================
# 主流程
# =========================
def main() -> None:
    ensure_dir(OUT_DIR)

    print("[1/8] 读取 CSV...")
    target_df = normalize_columns(read_csv_auto(TARGET_BASIC_CSV))
    physical_df = normalize_columns(read_csv_auto(PHYSICAL_CSV))
    model_df = normalize_columns(read_csv_auto(MODEL_CSV))
    function_df = normalize_columns(read_csv_auto(FUNCTION_CSV))
    func_part_df = normalize_columns(read_csv_auto(FUNC_PART_MAP_CSV))

    physical_df = physical_df.rename(columns={
        "部件ID（命名规则：BJ+四位数，范围BJ0001~ BJ9999。）": "部件ID"
    })
    function_df = function_df.rename(columns={
        "功能ID（命名规则：GN+四位数，范围GN0001~ GN9999。）": "功能ID"
    })

    print("[2/8] 处理 3.2 -> STL 绝对路径映射...")
    model_df["三维模型数据文件"] = model_df["三维模型数据文件"].map(safe_str)
    model_df["stl_abs_path"] = model_df["三维模型数据文件"].map(
        lambda x: str((STL_ROOT / x).resolve()) if x else ""
    )

    print("[3/8] 构建层级、名称、功能映射...")
    children_map = build_children_map(physical_df)
    name_map = build_name_map(physical_df)
    func_map = build_function_maps(function_df, func_part_df)

    print("[4/8] 汇总基础表...")
    merged = physical_df.merge(
        model_df[["目标ID", "部件ID", "三维模型数据文件", "stl_abs_path"]],
        how="left",
        on=["目标ID", "部件ID"],
    ).merge(
        target_df[["目标ID", "目标名称", "描述", "主要功能", "国家", "所属军种", "服役时间"]],
        how="left",
        on=["目标ID"],
    )

    print("[5/8] 提取 STL 几何字段...")
    rows: List[Dict[str, Any]] = []
    total = len(merged)

    for idx, (_, row) in enumerate(merged.iterrows(), start=1):
        item = dict(row)

        part_id = safe_str(item.get("部件ID"))
        part_name = safe_str(item.get("部件名称"))
        parent_id = safe_str(item.get("父部件ID"))
        parent_name = name_map.get(parent_id, "")

        stl_abs_path = safe_str(item.get("stl_abs_path"))
        stl_exists = bool(stl_abs_path and Path(stl_abs_path).exists())

        children_ids = children_map.get(part_id, [])
        children_names = [name_map.get(x, "") for x in children_ids]
        fmap = func_map.get(part_id, {"ids": [], "names": []})

        is_virtual_part = int((not stl_exists) and (len(children_ids) > 0))

        item["父部件名称"] = parent_name
        item["children_ids"] = ",".join(children_ids)
        item["children_names"] = ",".join([x for x in children_names if x])
        item["mapped_function_ids"] = ",".join(fmap["ids"])
        item["mapped_function_names"] = ",".join([x for x in fmap["names"] if x])
        item["has_stl_file"] = int(stl_exists)
        item["is_virtual_part"] = is_virtual_part

        print(f"  [{idx}/{total}] {part_id} {part_name} | has_stl={int(stl_exists)} | virtual={is_virtual_part}")

        if stl_exists:
            geo = extract_stl_features(Path(stl_abs_path))
            item.update(geo)
        else:
            item["mesh_loaded"] = 0
            item["geometry_error"] = ""

        rows.append(item)

    print("[6/8] 构建邻接、默认约束、语义角色...")
    records = rows
    row_by_id = {safe_str(r.get("部件ID")): r for r in records if safe_str(r.get("部件ID"))}

    target_ids = sorted(list({safe_str(r.get("目标ID")) for r in records if safe_str(r.get("目标ID"))}))
    neighbors_map: Dict[str, List[str]] = {}
    for tid in target_ids:
        submap = build_neighbors(records, tid)
        neighbors_map.update(submap)

    llm = LLMHelper(enabled=ENABLE_LLM, cache_path=LLM_CACHE_FILE)

    final_rows: List[Dict[str, Any]] = []

    for item in records:
        part_id = safe_str(item.get("部件ID"))
        edit_type = infer_edit_type(item)
        allowed_ops, forbidden_ops = infer_default_ops(edit_type, int(item.get("is_virtual_part", 0)))
        semantic_role = "virtual_assembly" if int(item.get("is_virtual_part", 0)) == 1 else "general_component"
        anchor_mode = infer_anchor_mode(item, semantic_role=semantic_role)
        clearance_min_mm = DEFAULT_CLEARANCE_MIN_MM

        llm_result = {}
        if llm.should_call(item):
            payload = {
                "target_info": {
                    "target_id": safe_str(item.get("目标ID")),
                    "target_name": safe_str(item.get("目标名称")),
                    "description": safe_str(item.get("描述")),
                    "main_function": safe_str(item.get("主要功能")),
                },
                "part_info": {
                    "part_id": part_id,
                    "part_name": safe_str(item.get("部件名称")),
                    "declared_parent_part_id": safe_str(item.get("父部件ID")),
                    "declared_parent_part_name": safe_str(item.get("父部件名称")),
                    "mapped_function_names": safe_str(item.get("mapped_function_names")),
                    "is_virtual_part": int(item.get("is_virtual_part", 0)),
                    "children_ids": [x for x in safe_str(item.get("children_ids")).split(",") if x],
                },
                "geometry_summary": {
                    "bbox_center": [
                        item.get("几何中心x(mm)"),
                        item.get("几何中心y(mm)"),
                        item.get("几何中心z(mm)"),
                    ],
                    "aabb_extents": [
                        item.get("长度(mm)"),
                        item.get("宽度(mm)"),
                        item.get("高度(mm)"),
                    ],
                    "obb_extents": [
                        item.get("OBB长度"),
                        item.get("OBB宽度"),
                        item.get("OBB高度"),
                    ],
                    "geometry_valid": item.get("是否通过验证"),
                },
                "default_suggestion": {
                    "edit_type": edit_type,
                    "anchor_mode": anchor_mode,
                    "allowed_ops": allowed_ops,
                    "forbidden_ops": forbidden_ops,
                    "clearance_min_mm": clearance_min_mm,
                },
            }

            llm_result = llm.infer_constraint_fields(payload)

            if llm_result.get("llm_success", 0) == 1:
                edit_type = safe_str(llm_result.get("edit_type")) or edit_type
                semantic_role = safe_str(llm_result.get("semantic_role")) or semantic_role
                anchor_mode = safe_str(llm_result.get("anchor_mode")) or anchor_mode
                allowed_ops = normalize_op_list(llm_result.get("allowed_ops", allowed_ops)) or allowed_ops
                forbidden_ops = normalize_op_list(llm_result.get("forbidden_ops", forbidden_ops)) or forbidden_ops
                llm_clearance = safe_float(llm_result.get("clearance_min_mm"))
                if llm_clearance is not None:
                    clearance_min_mm = llm_clearance

        anchor_mode = anchor_mode or infer_anchor_mode(item, semantic_role=semantic_role)

        item["edit_type"] = edit_type
        item["semantic_role"] = semantic_role
        item["anchor_mode"] = anchor_mode
        item["allowed_ops"] = ",".join(normalize_op_list(allowed_ops))
        item["forbidden_ops"] = ",".join(normalize_op_list(forbidden_ops))
        item["clearance_min_mm"] = clearance_min_mm
        item["llm_called"] = llm_result.get("llm_called", 0)
        item["llm_cache_hit"] = llm_result.get("llm_cache_hit", 0)
        item["llm_success"] = llm_result.get("llm_success", 0)
        item["llm_response_source"] = llm_result.get("llm_response_source", "disabled" if not ENABLE_LLM else "")
        item["llm_error"] = llm_result.get("llm_error", "")
        item["semantic_note"] = safe_str(llm_result.get("semantic_note", ""))

        final_rows.append(item)

    print("[7/8] 推断 attachment/follow 联动关系...")
    attachment_links = infer_attachment_links(final_rows, neighbors_map, llm)
    linked_children_map = build_linked_children_map(attachment_links, row_by_id)

    print("[8/8] 导出 master 与 constraints...")
    part_constraints: List[Dict[str, Any]] = []

    for item in final_rows:
        part_id = safe_str(item.get("部件ID"))
        part_name = safe_str(item.get("部件名称"))

        primary_axis = choose_primary_axis(item)
        symmetry_group = infer_symmetry_group(item)
        neighbors = neighbors_map.get(part_id, [])

        attachment_parent_part_id = ""
        attachment_parent_part_name = ""
        link_type = ""
        follow_transform_of = ""
        follow_ops: List[str] = []
        link_source = ""
        link_confidence = 0.0
        attachment_parent_candidates: List[Dict[str, Any]] = []
        linked_children = linked_children_map.get(part_id, {}).get("ids", [])
        linked_children_names = linked_children_map.get(part_id, {}).get("names", [])

        if part_id in attachment_links:
            link = attachment_links[part_id]
            attachment_parent_part_id = safe_str(link.get("attachment_parent_part_id"))
            attachment_parent_part_name = safe_str(link.get("attachment_parent_part_name"))
            link_type = safe_str(link.get("link_type"))
            follow_transform_of = safe_str(link.get("follow_transform_of"))
            follow_ops = normalize_op_list(link.get("follow_ops", []))
            link_source = safe_str(link.get("link_source"))
            link_confidence = float(link.get("link_confidence", 0.0) or 0.0)
            attachment_parent_candidates = list(link.get("attachment_parent_candidates", []) or [])

            if not safe_str(item.get("anchor_mode")):
                item["anchor_mode"] = "parent_attach"

        allowed_ops = normalize_op_list(item.get("allowed_ops", ""))
        forbidden_ops = normalize_op_list(item.get("forbidden_ops", ""))

        if int(item.get("is_virtual_part", 0)) == 1:
            if "no_direct_edit" not in forbidden_ops:
                forbidden_ops.append("no_direct_edit")
            allowed_ops = [x for x in allowed_ops if x in {"view", "select", "hide"}]

        forbidden_ops = [x for x in forbidden_ops if x not in allowed_ops or x in {"uniform_scale", "delete_core"}]

        item["primary_axis"] = json.dumps(primary_axis, ensure_ascii=False)
        item["symmetry_group"] = symmetry_group
        item["neighbors"] = json.dumps(neighbors, ensure_ascii=False)
        item["allowed_ops"] = ",".join(allowed_ops)
        item["forbidden_ops"] = ",".join(forbidden_ops)
        item["attachment_parent_part_id"] = attachment_parent_part_id
        item["attachment_parent_part_name"] = attachment_parent_part_name
        item["link_type"] = link_type
        item["follow_transform_of"] = follow_transform_of
        item["follow_ops"] = ",".join(follow_ops)
        item["link_source"] = link_source
        item["link_confidence"] = link_confidence
        item["linked_children"] = ",".join(linked_children)
        item["linked_children_names"] = ",".join(linked_children_names)
        item["attachment_parent_candidates"] = json.dumps(attachment_parent_candidates, ensure_ascii=False)

        constraint_obj = {
            "target_id": safe_str(item.get("目标ID")),
            "part_id": part_id,
            "part_name": part_name,

            # 原始结构父件：保留，但不等于联动父件
            "parent_part_id": safe_str(item.get("父部件ID")),
            "parent_part_name": safe_str(item.get("父部件名称")),

            # 显式弱提示字段
            "declared_parent_part_id": safe_str(item.get("父部件ID")),
            "declared_parent_part_name": safe_str(item.get("父部件名称")),

            "edit_type": safe_str(item.get("edit_type")),
            "primary_axis": primary_axis,
            "anchor_mode": safe_str(item.get("anchor_mode")),
            "symmetry_group": symmetry_group,
            "neighbors": neighbors,
            "allowed_ops": allowed_ops,
            "forbidden_ops": forbidden_ops,
            "clearance_min_mm": safe_float(item.get("clearance_min_mm")) or DEFAULT_CLEARANCE_MIN_MM,
            "has_stl_file": bool(int(item.get("has_stl_file", 0))),
            "is_virtual_part": bool(int(item.get("is_virtual_part", 0))),
            "geometry_valid": bool(int(item.get("是否通过验证", 0) or 0)),
            "geometry": {
                "bbox_center": [
                    item.get("几何中心x(mm)"),
                    item.get("几何中心y(mm)"),
                    item.get("几何中心z(mm)"),
                ],
                "center_mass": [
                    item.get("质心x"),
                    item.get("质心y"),
                    item.get("质心z"),
                ],
                "aabb_extents": [
                    item.get("长度(mm)"),
                    item.get("宽度(mm)"),
                    item.get("高度(mm)"),
                ],
            },
            "function_names": [x for x in safe_str(item.get("mapped_function_names")).split(",") if x],
            "semantic_note": safe_str(item.get("semantic_note")),
            "semantic_role": safe_str(item.get("semantic_role")),

            # 联动关系
            "attachment_parent_part_id": attachment_parent_part_id,
            "attachment_parent_part_name": attachment_parent_part_name,
            "link_type": link_type,
            "follow_transform_of": follow_transform_of,
            "follow_ops": follow_ops,
            "link_source": link_source,
            "link_confidence": round(link_confidence, 4),
            "attachment_parent_candidates": attachment_parent_candidates,
            "linked_children": linked_children,
            "linked_children_names": linked_children_names,
        }
        part_constraints.append(constraint_obj)

    master_df = pd.DataFrame(final_rows)
    master_df.to_csv(MASTER_CSV, index=False, encoding="utf-8-sig")
    MASTER_JSON.write_text(
        json.dumps(master_df.to_dict(orient="records"), ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )
    CONSTRAINTS_JSON.write_text(
        json.dumps(part_constraints, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )

    print("[DONE]")
    print(f"[OK] master csv : {MASTER_CSV}")
    print(f"[OK] master json: {MASTER_JSON}")
    print(f"[OK] constraints: {CONSTRAINTS_JSON}")
    if ENABLE_LLM:
        print(f"[OK] llm cache  : {LLM_CACHE_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[FATAL ERROR]")
        print(f"{type(e).__name__}: {e}")
        print(traceback.format_exc())
        raise