from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SummaryRequestItem:
    item_num: int
    title: str
    text: str


@dataclass(frozen=True)
class SummaryResult:
    lede: str
    summaries: dict[int, str]


class LlmProvider(Protocol):
    model: str

    def summarize(self, *, system_prompt: str, items: list[SummaryRequestItem]) -> SummaryResult: ...

    def chat(
        self,
        *,
        system_prompt: str,
        message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str: ...
