from __future__ import annotations

import httpx

from briefing.config import LlmConfig
from briefing.llm.base import SummaryRequestItem, SummaryResult
from briefing.llm.parse import parse_summary_response


class OpenAICompatProvider:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        self.model = config.model

    def summarize(self, *, system_prompt: str, items: list[SummaryRequestItem]) -> SummaryResult:
        if not items:
            return SummaryResult(lede="", summaries={})

        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": build_summary_user_message(items)},
            ],
        }
        response = httpx.post(
            self.config.base_url.rstrip("/") + "/chat/completions",
            json=payload,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = parse_summary_response(str(content), item_count=len(items))
        if parsed is None:
            return SummaryResult(lede="", summaries={})
        return parsed


def build_summary_user_message(items: list[SummaryRequestItem]) -> str:
    lines = [
        f"You have {len(items)} news items. Respond with ONLY a JSON object, no markdown fences, no preamble, in this shape:",
        "",
        '{"lede": "optional 1-2 sentence section opener, or empty string", "summaries": [{"item_num": 1, "summary": "..."}]}',
        "",
        "Items:",
    ]
    for item in items:
        text = item.text.strip() or item.title
        lines.extend(
            [
                f"{item.item_num}. Title: {item.title}",
                f"   Text: {text}",
                "",
            ]
        )
    return "\n".join(lines).strip()
