# STL 文本驱动变更 Demo 报告

## 输入概况
- 输入 Excel: D:\bica\k-8\STL-Change\stl_demo\data\metadata\airbus-a320neo_original.xlsx
- 扫描到的 STL 数量: 50
- 最终 STL 输出目录: D:\bica\k-8\STL-Change\stl_demo\output\final_stl
- 修改后 Excel: D:\bica\k-8\STL-Change\stl_demo\output\excels\updated_parts.xlsx
- 变更表 Excel: D:\bica\k-8\STL-Change\stl_demo\output\excels\change_table.xlsx

## Excel Schema 识别结果
```json
{
  "model_col": "模型名称",
  "object_type_col": "对象类型",
  "category_col": "部件类别",
  "name_col": "模型名称",
  "file_col": "部件文件",
  "node_col": "节点名称",
  "dim_cols": [
    "长度",
    "宽度",
    "高度"
  ],
  "dim_axis_map": {
    "x": [
      "长度"
    ],
    "y": [
      "宽度"
    ],
    "z": [
      "高度"
    ]
  },
  "pos_cols": [
    "位置X",
    "位置Y",
    "位置Z"
  ],
  "pos_axis_map": {
    "x": [
      "位置X"
    ],
    "y": [
      "位置Y"
    ],
    "z": [
      "位置Z"
    ]
  }
}
```

## 情报文本
- 关于某型窄体客机外形改型方案的综合判断。结合现有平台构型特征与改型需求分析，可以明确认为，本次改型不是局部微调，而是在保持基本布局不变的前提下，对若干关键外形区域进行可明显识别的强化式修订。改型目标不是仅形成细微差异，而是要在三维外形上形成清晰、直观、可对比展示的改型特征，使观察者能够在渲染结果中直接识别出机体主段、翼面外缘、背部附加结构以及动力外形等区域的明显变化。

首先，机身主段应作为本次改型的核心变化区域。现有平台中段承担客舱容积、设备布置与结构过渡等多重作用，也是最适合形成显著外观差异的位置。因此，改型应优先考虑对机身主段进行较明显的延展处理，使机体中部纵向比例发生可见变化，而不是仅做难以察觉的小幅拉伸。处理后的效果应能够在侧视和俯视角度下表现出更长、更饱满的中段外形特征，从而形成整机轮廓上的第一视觉差异点。

其次，翼面外缘应进行比原方案更积极的修订。此次改型不应停留在“轻微翼尖优化”的层面，而应在保持主翼总体位置不变的基础上，对外段翼面和翼尖区域做肉眼可识别的尺度增强或形态外扩。其目标是让左右翼的外缘轮廓在渲染结果中明显区别于原始构型，尤其在俯视视角下，应能体现出更舒展、更外扩的翼尖特征，使机翼成为第二个显著改型区域。

再次，机身背部中前段应新增一处存在感更强的附加整流结构。与原始平台相比，该新增结构不应过于克制，而应在尺寸和体量上达到能够清楚辨识的程度，使观察者能够一眼区分“原始机背轮廓”和“改型后机背轮廓”。这一新增部件应被理解为任务设备舱、通信整流罩或附加航电背脊等外部结构，其位置应尽量位于机背中前部相对醒目的区域，从而在侧视和斜视角度中都能形成稳定的视觉特征。

动力系统外形也应同步增强。若本次平台改型强调任务能力提升，则发动机短舱及其邻近区域不宜仅做轻微放大，而应进行更明确的增量式外形强化，使动力单元在机翼下方的体积感和存在感明显提升。改型后的短舱外轮廓应比原始状态更饱满、更粗壮，使其在近距离渲染图中形成清晰可见的差异，而不是需要反复比对后才能发现的细节变化。

此外，为了增强整机改型样本的展示效果，尾部局部翼面或尾翼邻近结构也可以进行适度配合性调整，但其作用主要是服务整体协调，不必作为唯一主改区域。整机改型应始终围绕“机身主段明显延展、翼尖外缘明显增强、背部新增醒目整流结构、发动机短舱明显放大”这四个核心变化点展开，确保改型结果在整体轮廓、局部体量和附加结构三个层面同时形成足够强的可视差异。

综合判断，本次改型样本应被理解为一种面向展示与对比验证的强化型外形修订方案。它不追求高度保守的工程收敛状态，而是强调改型结果在视觉上必须清楚、明确、稳定可辨。最终效果应使原始模型与改型模型并列展示时，观察者无需借助标注说明，也能够直接识别出机身中段被拉长、翼尖外缘被放大、机背新增附加结构、发动机外形更为饱满这几项主要变化。

## 变更意图
```json
{
  "changes": [
    {
      "target_part": "geometry_0__part_01.stl",
      "op": "scale",
      "params": {
        "x": 1.15,
        "y": 1.0,
        "z": 1.0
      },
      "reason": "机身主段明显延展，增强纵向比例"
    },
    {
      "target_part": "geometry_0__part_14.stl",
      "op": "scale",
      "params": {
        "x": 1.2,
        "y": 1.1,
        "z": 1.0
      },
      "reason": "翼尖外缘明显外扩，增强俯视可见性"
    },
    {
      "target_part": "geometry_0__part_16.stl",
      "op": "add",
      "params": {
        "source_part": "geometry_0__part_16.stl",
        "offset": {
          "x": 0.0,
          "y": 0.08,
          "z": 0.0
        }
      },
      "reason": "在机背中前段新增醒目整流结构"
    },
    {
      "target_part": "geometry_0__part_33.stl",
      "op": "scale",
      "params": {
        "x": 1.25,
        "y": 1.25,
        "z": 1.25
      },
      "reason": "发动机短舱明显放大，增强体积感和存在感"
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
      "target_part": "geometry_0__part_01.stl",
      "op": "scale",
      "params": {
        "x": 1.15,
        "y": 1.0,
        "z": 1.0
      },
      "reason": "机身主段明显延展，增强纵向比例"
    }
  },
  {
    "index": 1,
    "valid": true,
    "errors": [],
    "change": {
      "target_part": "geometry_0__part_14.stl",
      "op": "scale",
      "params": {
        "x": 1.2,
        "y": 1.1,
        "z": 1.0
      },
      "reason": "翼尖外缘明显外扩，增强俯视可见性"
    }
  },
  {
    "index": 2,
    "valid": true,
    "errors": [],
    "change": {
      "target_part": "geometry_0__part_16.stl",
      "op": "add",
      "params": {
        "source_part": "geometry_0__part_16.stl",
        "offset": {
          "x": 0.0,
          "y": 0.08,
          "z": 0.0
        }
      },
      "reason": "在机背中前段新增醒目整流结构"
    }
  },
  {
    "index": 3,
    "valid": true,
    "errors": [],
    "change": {
      "target_part": "geometry_0__part_33.stl",
      "op": "scale",
      "params": {
        "x": 1.25,
        "y": 1.25,
        "z": 1.25
      },
      "reason": "发动机短舱明显放大，增强体积感和存在感"
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
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\geometry_0__part_01.stl"
    ],
    "warnings": [],
    "message": "scale success",
    "target_part": "geometry_0__part_01.stl",
    "op": "scale"
  },
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\geometry_0__part_14.stl"
    ],
    "warnings": [],
    "message": "scale success",
    "target_part": "geometry_0__part_14.stl",
    "op": "scale"
  },
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\geometry_0__part_16_added_001.stl"
    ],
    "warnings": [],
    "message": "add(copy) success",
    "target_part": "geometry_0__part_16.stl",
    "op": "add"
  },
  {
    "success": true,
    "output_files": [
      "D:\\bica\\k-8\\STL-Change\\stl_demo\\output\\final_stl\\geometry_0__part_33.stl"
    ],
    "warnings": [],
    "message": "scale success",
    "target_part": "geometry_0__part_33.stl",
    "op": "scale"
  }
]
```

## 成功项 (4)
- scale geometry_0__part_01.stl: scale success
- scale geometry_0__part_14.stl: scale success
- add geometry_0__part_16.stl: add(copy) success
- scale geometry_0__part_33.stl: scale success

## 失败项 (0)

## Warnings
- 无