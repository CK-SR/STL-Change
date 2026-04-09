from __future__ import annotations

from typing import Any, Dict, List
from app.llm.base import BaseLLMClient


class MockLLMClient(BaseLLMClient):
    """Keyword based mock LLM to keep full pipeline runnable offline."""

    def _pick_part(self, text: str, part_summary: List[Dict[str, Any]]) -> str:
        if not part_summary:
            return ""
        text_lower = text.lower()
        for part in part_summary:
            category = str(part.get("category", "")).lower()
            if category and category in text_lower:
                return part["part_name"]
        return part_summary[0]["part_name"]

    def _pick_source(self, part_summary: List[Dict[str, Any]]) -> str:
        return part_summary[0]["part_name"] if part_summary else ""

    def generate_change_intent(
        self,
        intelligence_texts: List[str],
        part_summary: List[Dict[str, Any]],
        prompt: str,
    ) -> Dict[str, Any]:
        changes: List[Dict[str, Any]] = []

        for text in intelligence_texts:
            target = self._pick_part(text, part_summary)
            if any(k in text for k in ["增大", "加宽", "扩大"]):
                op = "scale"
                params = {"x": 1.1, "y": 1.05, "z": 1.0}
            elif any(k in text for k in ["下移", "右移", "左移", "上移"]):
                op = "translate"
                dx = -0.05 if "左移" in text else (0.05 if "右移" in text else 0.0)
                dy = -0.05 if "下移" in text else (0.05 if "上移" in text else 0.0)
                params = {"x": dx, "y": dy, "z": 0.0}
            elif any(k in text for k in ["旋转", "上翘"]):
                op = "rotate"
                params = {"axis": "z", "degrees": 8.0}
            elif "删除" in text:
                op = "delete"
                params = {}
            elif "新增" in text:
                op = "add"
                source = self._pick_source(part_summary)
                params = {"source_part": source, "offset": {"x": 0.1, "y": 0.0, "z": 0.0}}
            else:
                op = "translate"
                params = {"x": 0.01, "y": 0.0, "z": 0.0}

            changes.append(
                {
                    "target_part": target,
                    "op": op,
                    "params": params,
                    "reason": text,
                }
            )

        return {"changes": changes}
