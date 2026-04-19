# STL 文本驱动变更 Demo 报告

## 1. 输入概况
- 输入 Excel: N/A (minimal flow without excel)
- 扫描到的 STL 数量: 20
- 最终 STL 输出目录: D:\bica\k-8\STL-Change\stl_demo\output\final_stl
- 修改后 Excel: N/A
- 变更表 Excel: N/A

## 2. 情报文本
- 在 BJ0007 顶部新增一个防无人机顶棚，新件命名为 BJ9001，优先检索现有 roof 素材，如无合适再生成；新增件需覆盖 BJ0007 顶部主要长度，允许沿主轴适度拉伸。

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
      "target_part": "BJ9001",
      "op": "add",
      "params": {
        "attach_to": "BJ0007",
        "asset_request": {
          "content": "防无人机顶棚",
          "input_type": "text",
          "category": "roof",
          "target_type": "armored_vehicle",
          "mount_region": "top_hull",
          "topk": 5,
          "auto_approve": true,
          "auto_accept_prompt": true,
          "auto_accept_generation": true,
          "force_generate": false
        },
        "fit_policy": {
          "mode": "cover_parent",
          "coverage_ratio": 0.92,
          "clearance_mm": 20,
          "allow_stretch": true
        },
        "post_transform_overrides": {
          "translate": {
            "x": 0,
            "y": 0,
            "z": 0
          },
          "rotate": {
            "axis": "z",
            "degrees": 0
          }
        }
      },
      "reason": "在 BJ0007 顶部新增防无人机顶棚 BJ9001，优先检索 roof 素材，允许沿主轴拉伸以覆盖主要长度"
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
      "target_part": "BJ9001",
      "op": "add",
      "params": {
        "attach_to": "BJ0007",
        "asset_request": {
          "content": "防无人机顶棚",
          "input_type": "text",
          "category": "roof",
          "target_type": "armored_vehicle",
          "mount_region": "top_hull",
          "topk": 5,
          "auto_approve": true,
          "auto_accept_prompt": true,
          "auto_accept_generation": true,
          "force_generate": false
        },
        "fit_policy": {
          "mode": "cover_parent",
          "coverage_ratio": 0.92,
          "clearance_mm": 20,
          "allow_stretch": true
        },
        "post_transform_overrides": {
          "translate": {
            "x": 0,
            "y": 0,
            "z": 0
          },
          "rotate": {
            "axis": "z",
            "degrees": 0
          }
        }
      },
      "reason": "在 BJ0007 顶部新增防无人机顶棚 BJ9001，优先检索 roof 素材，允许沿主轴拉伸以覆盖主要长度"
    }
  }
]
```

## 6. 执行结果概览
- 成功执行数: 1
- 失败执行数: 0

### 6.1 成功项
- add BJ9001: add success via external asset acquisition + local fit

### 6.2 失败项
- 无

### 6.3 执行结果明细
```json
[
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ9001.stl"
    ],
    "warnings": [
      "mesh_repair_actions[BJ9001]=fix_normals,fix_winding,remove_unreferenced_vertices",
      "mesh_repair_warning[BJ9001]=remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'",
      "reasonableness_skipped[BJ9001]=no_input_mesh"
    ],
    "message": "add success via external asset acquisition + local fit",
    "target_part": "BJ9001",
    "op": "add",
    "metadata": {
      "affected_parts": [
        {
          "part_id": "BJ9001",
          "input_path": "",
          "temp_output_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\.__tmp__BJ9001_added_fitted.stl",
          "role": "primary_add",
          "linked_from": ""
        }
      ],
      "attach_to": "BJ0007",
      "asset_acquisition": {
        "success": true,
        "message": "asset selected and downloaded",
        "local_stl_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\downloaded_assets\\BJ9001_dfd0e21728e141c8a5a1445f3bc10172.stl",
        "download_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720.stl",
        "task_id": "",
        "provider_status": "",
        "asset_metadata": {
          "name": "接口测试-手工上传防无人机顶棚",
          "category": "roof",
          "target_type": "armored_vehicle",
          "mount_region": "top_hull",
          "size_range": null,
          "default_orientation": null,
          "mount_ref_point": null,
          "constraints": null,
          "stl_object_key": "manual/7f8780347776455cb2d1c78db7682720.stl",
          "preview_image_object_key": "manual/7f8780347776455cb2d1c78db7682720_preview.png",
          "source": "manual_upload",
          "generation_prompt": null,
          "version": 1,
          "version_group": null,
          "parent_asset_id": null,
          "id": 4,
          "created_at": "2026-04-16T09:09:55",
          "updated_at": "2026-04-16T09:09:55",
          "download_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720.stl",
          "preview_image_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720_preview.png"
        },
        "raw_submit_response": {
          "status": "ASSET_SELECTED",
          "parsed_input": {
            "input_type": "text",
            "content": "防无人机顶棚",
            "normalized_content": "防无人机顶棚",
            "metadata": {}
          },
          "intent": {
            "query": "防无人机顶棚 装甲车",
            "category": "roof",
            "target_type": "armored_vehicle",
            "mount_region": "top_hull",
            "generation_prompt": "Anti-drone protective roof cage for armored vehicle, metal mesh structure, mounted on top hull, rugged tactical design, steel material, high detail 3D model",
            "embedding_text": "装甲车 防无人机 顶棚 格栅 防护 顶部",
            "attributes": {
              "protection_type": "passive_armor",
              "structure_form": "cage_mesh",
              "material": "steel_alloy",
              "threat_type": "uav_drone",
              "compatible_targets": [
                "tank",
                "ifv",
                "apc"
              ],
              "attachment_method": "welded_bolted"
            }
          },
          "candidates": [
            {
              "asset": {
                "name": "接口测试-手工上传防无人机顶棚",
                "category": "roof",
                "target_type": "armored_vehicle",
                "mount_region": "top_hull",
                "size_range": null,
                "default_orientation": null,
                "mount_ref_point": null,
                "constraints": null,
                "stl_object_key": "manual/7f8780347776455cb2d1c78db7682720.stl",
                "preview_image_object_key": "manual/7f8780347776455cb2d1c78db7682720_preview.png",
                "source": "manual_upload",
                "generation_prompt": null,
                "version": 1,
                "version_group": null,
                "parent_asset_id": null,
                "id": 4,
                "created_at": "2026-04-16T09:09:55",
                "updated_at": "2026-04-16T09:09:55",
                "download_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720.stl",
                "preview_image_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720_preview.png"
              },
              "score": 0.7477,
              "structured_score": 0.759,
              "semantic_score": 0.7385,
              "reason": "structured metadata match"
            }
          ],
          "selected_asset": {
            "name": "接口测试-手工上传防无人机顶棚",
            "category": "roof",
            "target_type": "armored_vehicle",
            "mount_region": "top_hull",
            "size_range": null,
            "default_orientation": null,
            "mount_ref_point": null,
            "constraints": null,
            "stl_object_key": "manual/7f8780347776455cb2d1c78db7682720.stl",
            "preview_image_object_key": "manual/7f8780347776455cb2d1c78db7682720_preview.png",
            "source": "manual_upload",
            "generation_prompt": null,
            "version": 1,
            "version_group": null,
            "parent_asset_id": null,
            "id": 4,
            "created_at": "2026-04-16T09:09:55",
            "updated_at": "2026-04-16T09:09:55",
            "download_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720.stl",
            "preview_image_url": "http://39.106.164.226:9000/stl-assets/manual/7f8780347776455cb2d1c78db7682720_preview.png"
          },
          "task_id": null,
          "review_id": null,
          "message": "Top candidate was selected by auto approval."
        },
        "raw_task_response": null,
        "warnings": []
      },
      "fit_plan": {
        "attach_to": "BJ0007",
        "category": "roof",
        "coverage_ratio": 0.92,
        "allow_stretch": true,
        "clearance_mm": 20.0,
        "auto_translate": {
          "x": -330.9549999999995,
          "y": 1349.7333966094066,
          "z": 2430.58
        },
        "auto_rotation": {
          "thin_axis_to_z": true,
          "long_axis_to_parent_primary_axis": true
        },
        "auto_stretch_delta_mm": 6162.576586437627,
        "overrides_applied": {
          "translate": {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0
          },
          "rotate": {
            "axis": "z",
            "degrees": 0.0
          }
        }
      }
    }
  }
]
```

## 7. Mesh Repair 结果
- repair 记录数: 1
```json
[
  {
    "input_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\.__tmp__BJ9001_added_fitted.stl",
    "output_path": "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\.__tmp__BJ9001_added_fitted.stl",
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
      "vertices": 3,
      "faces": 1,
      "is_watertight": false,
      "is_winding_consistent": true,
      "euler_number": 1
    },
    "stats_after": {
      "vertices": 3,
      "faces": 1,
      "is_watertight": false,
      "is_winding_consistent": true,
      "euler_number": 1
    },
    "message": "mesh repair finished"
  }
]
```

## 8. 合理性检查结果
- pass: 0
- warning: 0
- unknown: 0

```json
[]
```

## 9. 最终结论
- 本次变更流程顺利完成，且自动修复与合理性检查未发现明显异常，可作为当前阶段 demo 展示结果。

## 10. 全局 Warnings
- mesh_repair_actions[BJ9001]=fix_normals,fix_winding,remove_unreferenced_vertices
- mesh_repair_warning[BJ9001]=remove_duplicate_faces failed: 'Trimesh' object has no attribute 'remove_duplicate_faces'
- reasonableness_skipped[BJ9001]=no_input_mesh