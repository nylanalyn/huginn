from __future__ import annotations

from briefing.llm.base import SummaryRequestItem, SummaryResult


class NullLlmProvider:
    model = "null"

    def summarize(self, *, system_prompt: str, items: list[SummaryRequestItem]) -> SummaryResult:
        return SummaryResult(lede="", summaries={})
