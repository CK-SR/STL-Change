from __future__ import annotations

import logging
from typing import List

from app.models import ChangeIntent
from app.llm.base import BaseLLMClient
from app.services.prompt_builder import build_change_intent_prompt

logger = logging.getLogger(__name__)


def generate_change_intent(
    llm_client: BaseLLMClient,
    intelligence_texts: List[str],
    part_summary: List[dict],
) -> ChangeIntent:
    prompt = build_change_intent_prompt()
    try:
        raw = llm_client.generate_change_intent(intelligence_texts, part_summary, prompt)
        return ChangeIntent.model_validate(raw)
    except Exception as exc:
        logger.warning("LLM generation failed, fallback to empty intent: %s", exc)
        return ChangeIntent(changes=[])
