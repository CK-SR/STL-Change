# STL 文本驱动变更 Demo 报告

## 1. 输入概况
- 输入 Excel: N/A (minimal flow without excel)
- 扫描到的 STL 数量: 20
- 最终 STL 输出目录: D:\bica\k-8\STL-Change\stl_demo\output\final_stl
- 修改后 Excel: N/A
- 变更表 Excel: N/A

## 2. 情报文本
- 针对目标车辆 MB576055，执行一轮显著外观调整：
1. 将炮塔向左旋转 35 度。
要求：禁止整体缩放，仅允许对指定部件做局部受约束编辑，其余部件保持不变。

## 3. 约束来源
```json
{
  "source": "part_constraints.json"
}
```

## 4. 原始变更意图
```json
{
  "changes": [
    {
      "target_part": "BJ0013",
      "op": "rotate",
      "params": {
        "axis": "z",
        "degrees": 35
      },
      "reason": "情报文本要求将炮塔向左旋转 35 度"
    }
  ]
}
```

## 5. 校验结果概览
- 有效变更数: 1
- 无效变更数: 0

### 5.1 详细校验结果
```json
[
  {
    "index": 0,
    "valid": true,
    "errors": [],
    "change": {
      "target_part": "BJ0013",
      "op": "rotate",
      "params": {
        "axis": "z",
        "degrees": 35
      },
      "reason": "情报文本要求将炮塔向左旋转 35 度"
    }
  }
]
```

## 6. 执行结果概览
- 成功执行数: 1
- 失败执行数: 0

### 6.1 成功项
- rotate BJ0013: Rotated by 35.0 deg; use geometry.center_mass hint; anchor=axis_fixed(center-like)

### 6.2 失败项
- 无

### 6.3 执行结果明细
```json
[
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0013.stl"
    ],
    "warnings": [
      "anchor_point=[1567.133777, -1648.788886, 15661.488767]",
      "axis_used=[0.0, 0.0, 1.0]",
      "mesh_repair_actions=fix_normals,fix_winding,remove_unreferenced_vertices",
      "mesh_repair_warning=remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'",
      "reasonableness_status=warning"
    ],
    "message": "Rotated by 35.0 deg; use geometry.center_mass hint; anchor=axis_fixed(center-like)",
    "target_part": "BJ0013",
    "op": "rotate"
  }
]
```

## 7. Mesh Repair 结果
- repair 记录数: 1
```json
[
  {
    "input_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\.__tmp__BJ0013_rotated.stl",
    "output_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\.__tmp__BJ0013_rotated.stl",
    "success": true,
    "actions": [
      "fix_normals",
      "fix_winding",
      "remove_unreferenced_vertices"
    ],
    "warnings": [
      "remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'"
    ],
    "stats_before": {
      "vertices": 40431,
      "faces": 13477,
      "is_watertight": false,
      "is_winding_consistent": true,
      "euler_number": 13477
    },
    "stats_after": {
      "vertices": 40431,
      "faces": 13477,
      "is_watertight": false,
      "is_winding_consistent": true,
      "euler_number": 13477
    },
    "message": "mesh repair finished"
  }
]
```

## 8. 合理性检查结果
- pass: 0
- warning: 1
- unknown: 0

```json
[
  {
    "part_id": "BJ0013",
    "op": "rotate",
    "input_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0013.stl",
    "output_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\.__tmp__BJ0013_rotated.stl",
    "status": "warning",
    "checks": [
      {
        "name": "mesh_basic",
        "passed": true,
        "detail": "is_watertight=False, is_winding_consistent=True",
        "severity": "info"
      },
      {
        "name": "volume_change",
        "passed": true,
        "detail": "volume ratio skipped because old volume is too small (old=0.000000, new=0.000000)",
        "severity": "info"
      },
      {
        "name": "primary_axis_extent",
        "passed": true,
        "detail": "old_extent=5892.880, new_extent=4864.419, ratio=0.825",
        "severity": "info"
      },
      {
        "name": "collision",
        "passed": false,
        "detail": "AABB collision with neighbors: BJ0001, BJ0004, BJ0006, BJ0008, BJ0012, BJ0019",
        "severity": "error"
      },
      {
        "name": "clearance",
        "passed": true,
        "detail": "neighbor clearance looks acceptable",
        "severity": "info"
      },
      {
        "name": "symmetry_group",
        "passed": true,
        "detail": "no symmetry mates configured, symmetry check skipped",
        "severity": "info"
      }
    ],
    "warnings": [],
    "summary": "reasonableness check found high-risk issues"
  }
]
```

## 9. 最终结论
- 本次变更流程已完成，但合理性检查给出 warning，建议结合碰撞/间隙/对称性结果人工复核。

## 10. 全局 Warnings
- anchor_point=[1567.133777, -1648.788886, 15661.488767]
- axis_used=[0.0, 0.0, 1.0]
- mesh_repair_actions=fix_normals,fix_winding,remove_unreferenced_vertices
- mesh_repair_warning=remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'
- reasonableness_status=warning