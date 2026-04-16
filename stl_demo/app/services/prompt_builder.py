from __future__ import annotations

import json
from typing import List, Dict


def build_change_intent_prompt(
    intelligence_texts: List[str],
    part_summary: List[Dict],
) -> str:
    intelligence_block = "\n".join([f"- {x}" for x in intelligence_texts if str(x).strip()])
    part_summary_json = json.dumps(part_summary, ensure_ascii=False, indent=2)

    return f"""
你是一名面向 STL 装备模型编辑的规划助手。
你的任务是：根据情报文本和结构化部件摘要，生成 STL 变更意图。

你必须遵守以下规则：
1. 只能输出 JSON。
2. 输出格式：
{{
  "changes": [
    {{
      "target_part": "部件ID或部件名称",
      "op": "scale|translate|rotate|delete|add|stretch",
      "params": {{}},
      "reason": "简短原因"
    }}
  ]
}}
3. 优先依据部件摘要中的 allowed_ops / forbidden_ops 决定操作。
4. 若部件是 structural_part，且需求是“加长/伸长/延长”，优先输出 stretch，而不是 uniform scale。
5. 若部件 forbidden_ops 包含 uniform_scale，则不要输出传统整体缩放。
6. rotate 可使用：
   - {{"axis":"x|y|z","degrees":15}}
   - 或 {{"axis_vector":[0,0,1],"degrees":15}}
7. stretch 使用：
   - {{"delta_mm": 30}}
8. translate 使用：
   - {{"x":10,"y":0,"z":0}}
9. 对虚拟部件、无直接编辑权限的部件，不要生成直接编辑操作。
10. 若信息不足，不要臆造复杂操作，可返回空 changes。

情报文本：
{intelligence_block}

结构化部件摘要：
{part_summary_json}
""".strip()