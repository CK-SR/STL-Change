# STL 文本驱动变更 Demo 报告

## 输入概况
- 输入 Excel: N/A (minimal flow without excel)
- 扫描到的 STL 数量: 20
- 最终 STL 输出目录: D:\bica\k-8\STL-Change\stl_demo\output\final_stl
- 修改后 Excel: N/A
- 变更表 Excel: N/A

## Excel Schema 识别结果
```json
{
  "source": "part_constraints.json"
}
```

## 情报文本
- 将 BJ0001 支架沿其主轴加长 30mm，固定底面不要移动。
将 BJ0002 围绕安装轴旋转 15 度。
不要对禁止整体缩放的部件做 uniform scale。

## 变更意图
```json
{
  "changes": [
    {
      "target_part": "BJ0002",
      "op": "rotate",
      "params": {
        "axis_vector": [
          0.0,
          1.0,
          0.0
        ],
        "degrees": 15
      },
      "reason": "用户指令要求围绕安装轴旋转 15 度，该部件允许 rotate 操作"
    }
  ]
}
```

## 校验结果
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
          0.0,
          1.0,
          0.0
        ],
        "degrees": 15
      },
      "reason": "用户指令要求围绕安装轴旋转 15 度，该部件允许 rotate 操作"
    }
  }
]
```

## 执行结果
```json
[
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\BJ0002_rotated.stl"
    ],
    "warnings": [
      "anchor_point=[-3613.973102, -1487.6298, 1248.919162]",
      "axis_used=[0.0, 1.0, 0.0]"
    ],
    "message": "Rotated by 15.0 deg; use min projection end along axis; center=preferred center hint",
    "target_part": "BJ0002",
    "op": "rotate"
  }
]
```

## 成功项 (1)
- rotate BJ0002: Rotated by 15.0 deg; use min projection end along axis; center=preferred center hint

## 失败项 (0)

## Warnings
- anchor_point=[-3613.973102, -1487.6298, 1248.919162]
- axis_used=[0.0, 1.0, 0.0]