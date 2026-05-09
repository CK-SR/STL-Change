from __future__ import annotations

import json

from typing import Any, Dict, List
from openai import OpenAI
from app.config import get_openai_api_key
from app.llm.base import BaseLLMClient


class OpenAICompatibleLLMClient(BaseLLMClient):
    def __init__(self, base_url: str, api_key: str | None, model_name: str) -> None:
        resolved_api_key = (api_key or get_openai_api_key()).strip()
        if not resolved_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required for LLM_MODE=openai")
        self.client = OpenAI(base_url=base_url, api_key=resolved_api_key)
        self.model_name = model_name

    def generate_change_intent(
        self,
        intelligence_texts: List[str],
        part_summary: List[Dict[str, Any]],
        prompt: str,
    ) -> Dict[str, Any]:
        user_content = (
            f"情报文本:\n{json.dumps(intelligence_texts, ensure_ascii=False, indent=2)}\n\n"
            f"部件摘要:\n{json.dumps(part_summary, ensure_ascii=False, indent=2)}"
        )
        resp = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        return json.loads(content)
