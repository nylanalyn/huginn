from __future__ import annotations

from briefing.llm.base import SummaryRequestItem, SummaryResult


class NullLlmProvider:
    model = "null"

    def summarize(self, *, system_prompt: str, items: list[SummaryRequestItem]) -> SummaryResult:
        return SummaryResult(lede="", summaries={})

    def chat(
        self,
        *,
        system_prompt: str,
        message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return ""
