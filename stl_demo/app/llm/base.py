from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseLLMClient(ABC):
    @abstractmethod
    def generate_change_intent(
        self,
        intelligence_texts: List[str],
        part_summary: List[Dict[str, Any]],
        prompt: str,
    ) -> Dict[str, Any]:
        raise NotImplementedError
