from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from briefing.sections.base import RenderedSection

LOG = logging.getLogger(__name__)

DISCORD_CONTENT_LIMIT = 2000
DEFAULT_TIMEOUT_SECONDS = 15


class DiscordWebhookError(RuntimeError):
    """Raised when webhook delivery fails."""


@dataclass(frozen=True)
class DiscordWebhookSender:
    webhook_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    min_delay_seconds: float = 1.0

    def send_sections(self, sections: list[RenderedSection]) -> list[str]:
        messages = split_sections_for_discord(sections)
        if not messages:
            messages = ["(empty briefing)"]

        with httpx.Client(timeout=self.timeout_seconds) as client:
            for index, message in enumerate(messages):
                if index:
                    time.sleep(self.min_delay_seconds)
                self._post_with_retries(client, message)
        return messages

    def _post_with_retries(self, client: httpx.Client, content: str) -> None:
        backoffs = [2.0, 4.0, 8.0]
        rate_limit_count = 0

        while True:
            response = client.post(self.webhook_url, json={"content": content})
            if response.status_code in {200, 204}:
                return

            if response.status_code == 429 and rate_limit_count < len(backoffs):
                retry_after = _retry_after_seconds(response)
                LOG.warning("Discord webhook rate limited; retrying after %.2fs", retry_after)
                time.sleep(retry_after)
                if rate_limit_count:
                    time.sleep(backoffs[rate_limit_count - 1])
                rate_limit_count += 1
                continue

            raise DiscordWebhookError(
                f"Discord webhook failed with HTTP {response.status_code}: "
                f"{_safe_response_text(response)}"
            )


def split_sections_for_discord(
    sections: list[RenderedSection],
    limit: int = DISCORD_CONTENT_LIMIT,
) -> list[str]:
    messages: list[str] = []
    current = ""

    for section in sections:
        section_text = _section_to_text(section)
        for chunk in _split_text(section_text, limit):
            candidate = _join_blocks(current, chunk)
            if current and len(candidate) > limit:
                messages.append(current)
                current = chunk
            else:
                current = candidate

    if current:
        messages.append(current)
    return messages


def _section_to_text(section: RenderedSection) -> str:
    body = "\n".join(section.lines) if section.lines else "(no items)"
    return f"{section.title}\n{body}"


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        pending = line
        while pending:
            separator_len = 1 if current else 0
            remaining = limit - len(current) - separator_len
            if remaining <= 0:
                chunks.append(current)
                current = ""
                continue

            piece = pending[:remaining]
            candidate = piece if not current else f"{current}\n{piece}"
            current = candidate
            pending = pending[remaining:]

            if pending:
                chunks.append(current)
                current = ""
    if current:
        chunks.append(current)
    return chunks


def _join_blocks(left: str, right: str) -> str:
    if not left:
        return right
    return f"{left}\n\n{right}"


def _retry_after_seconds(response: httpx.Response) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            LOG.warning("Discord returned invalid Retry-After header: %r", retry_after)

    try:
        data: dict[str, Any] = response.json()
    except ValueError:
        return 1.0

    value = data.get("retry_after", 1.0)
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 1.0


def _safe_response_text(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return "<empty response>"
    return text[:500]
