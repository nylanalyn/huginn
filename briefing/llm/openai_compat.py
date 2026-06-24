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

        content = self._chat_completion(
            system_prompt=system_prompt,
            message=build_summary_user_message(items),
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            response_format={"type": "json_object"} if self.config.json_mode else None,
        )
        parsed = parse_summary_response(str(content), item_count=len(items))
        if parsed is None:
            return SummaryResult(lede="", summaries={})
        return parsed

    def chat(
        self,
        *,
        system_prompt: str,
        message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        resolved_temperature = self.config.temperature if temperature is None else temperature
        return str(
            self._chat_completion(
                system_prompt=system_prompt,
                message=message,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=resolved_temperature,
            )
        ).strip()

    def _chat_completion(
        self,
        *,
        system_prompt: str,
        message: str,
        max_tokens: int,
        temperature: float,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.config.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        }
        if response_format is not None:
            payload["response_format"] = response_format
        response = httpx.post(
            self.config.base_url.rstrip("/") + "/chat/completions",
            json=payload,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])


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
