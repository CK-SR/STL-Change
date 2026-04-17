# STL 文本驱动变更 Demo 报告

## 1. 输入概况
- 输入 Excel: N/A (minimal flow without excel)
- 扫描到的 STL 数量: 20
- 最终 STL 输出目录: D:\bica\k-8\STL-Change\stl_demo\output\final_stl
- 修改后 Excel: N/A
- 变更表 Excel: N/A

## 2. 情报文本
- 将 BJ0001 支架沿其主轴加长 30mm，固定底面不要移动。
将 BJ0002 围绕安装轴旋转 15 度。
不要对禁止整体缩放的部件做 uniform scale。

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
      "target_part": "BJ0002",
      "op": "rotate",
      "params": {
        "axis_vector": [
          0,
          1,
          0
        ],
        "degrees": 15
      },
      "reason": "用户指令要求围绕安装轴旋转 15 度，且该部件允许 rotate 操作"
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
      "target_part": "BJ0002",
      "op": "rotate",
      "params": {
        "axis_vector": [
          0,
          1,
          0
        ],
        "degrees": 15
      },
      "reason": "用户指令要求围绕安装轴旋转 15 度，且该部件允许 rotate 操作"
    }
  }
]
```

## 6. 执行结果概览
- 成功执行数: 1
- 失败执行数: 0

### 6.1 成功项
- rotate BJ0002: Rotated by 15.0 deg; use min projection end along axis; center=preferred center hint

### 6.2 失败项
- 无

### 6.3 执行结果明细
```json
[
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0002_rotated.stl"
    ],
    "warnings": [
      "anchor_point=[-3613.973102, -1487.6298, 1248.919162]",
      "axis_used=[0.0, 1.0, 0.0]",
      "mesh_repair_actions=fix_normals,fix_winding,remove_unreferenced_vertices",
      "mesh_repair_warning=remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'",
      "reasonableness_status=warning"
    ],
    "message": "Rotated by 15.0 deg; use min projection end along axis; center=preferred center hint",
    "target_part": "BJ0002",
    "op": "rotate"
  }
]
```

## 7. Mesh Repair 结果
- repair 记录数: 1
```json
[
  {
    "input_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0002_rotated.stl",
    "output_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0002_rotated.stl",
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
      "vertices": 34704,
      "faces": 11568,
      "is_watertight": false,
      "is_winding_consistent": true,
      "euler_number": 11568
    },
    "stats_after": {
      "vertices": 34704,
      "faces": 11568,
      "is_watertight": false,
      "is_winding_consistent": true,
      "euler_number": 11568
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
    "part_id": "BJ0002",
    "op": "rotate",
    "input_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0002.stl",
    "output_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0002_rotated.stl",
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
        "detail": "old_extent=3048.710, new_extent=3048.710, ratio=1.000",
        "severity": "info"
      },
      {
        "name": "collision",
        "passed": false,
        "detail": "AABB collision with neighbors: BJ0001, BJ0004, BJ0005, BJ0006, BJ0007, BJ0020",
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
- anchor_point=[-3613.973102, -1487.6298, 1248.919162]
- axis_used=[0.0, 1.0, 0.0]
- mesh_repair_actions=fix_normals,fix_winding,remove_unreferenced_vertices
- mesh_repair_warning=remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'
- reasonableness_status=warning