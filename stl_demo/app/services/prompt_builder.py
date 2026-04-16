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

【最重要要求】
1. 逐条识别情报文本中的每一个“明确编辑请求”。
2. 对于每一个“可执行且目标明确”的请求，都必须输出一条对应的 change。
3. 不要因为只对其中一条更有把握，就忽略另一条同样明确、同样可执行的请求。
4. 若文本中出现部件ID（如 BJ0001），优先直接使用该 part_id 作为 target_part。
5. 若部件摘要中 allowed_ops 包含 stretch，且文本语义是“加长/伸长/延长”，必须优先输出 stretch。
6. 若 forbidden_ops 包含 uniform_scale，则禁止输出传统整体 scale(x,y,z)。

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
3. rotate 可使用：
   - {{"axis":"x|y|z","degrees":15}}
   - 或 {{"axis_vector":[0,0,1],"degrees":15}}
4. stretch 使用：
   - {{"delta_mm": 30}}
   - 若文本中已明确“沿主轴”，无需重复输出 direction_hint，系统会从约束摘要中读取 primary_axis / anchor_mode。
5. translate 使用：
   - {{"x":10,"y":0,"z":0}}
6. 对虚拟部件、无直接编辑权限的部件，不要生成直接编辑操作。
7. 只有在目标不明确、操作与约束冲突、或信息确实不足时，才能不输出该条变更。

情报文本：
{intelligence_block}

结构化部件摘要：
{part_summary_json}
""".strip()