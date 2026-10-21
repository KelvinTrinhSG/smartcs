from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.llm.client import LLMResult


@dataclass
class Usage:
    """Accumulates tokens and cost across every LLM/embedding call made for one request."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    def add(self, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += cost_usd

    def add_result(self, r: LLMResult) -> None:
        self.add(r.tokens_in, r.tokens_out, r.cost_usd)
