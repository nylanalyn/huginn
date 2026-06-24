from __future__ import annotations

from datetime import datetime
from typing import Any

from briefing.sections.base import RenderedSection, SectionCard
from briefing.utils.time import utc_now

EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096
MAX_EMBEDS_PER_MESSAGE = 10
MAX_MESSAGE_EMBED_CHARS = 6000

DEFAULT_COLOR = 0x5865F2  # Discord blurple
SECTION_COLORS = {
    "news": 0x3498DB,
    "tech": 0x2ECC71,
    "ai": 0x9B59B6,
    "local": 0xE67E22,
    "music": 0xE91E63,
    "weather": 0x1ABC9C,
    "calendar": 0xF1C40F,
}


def build_briefing_embeds(
    sections: list[RenderedSection],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Render sections as Discord embed payloads (JSON-shaped dicts)."""
    now = now or utc_now()
    embeds: list[dict[str, Any]] = []
    for section in sections:
        embeds.extend(_section_embeds(section, now))
    return embeds


def batch_embeds_for_messages(embeds: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group embeds into messages within Discord's per-message embed limits."""
    messages: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for embed in embeds:
        size = _embed_chars(embed)
        too_many = len(current) >= MAX_EMBEDS_PER_MESSAGE
        too_big = current_chars + size > MAX_MESSAGE_EMBED_CHARS
        if current and (too_many or too_big):
            messages.append(current)
            current = []
            current_chars = 0
        current.append(embed)
        current_chars += size
    if current:
        messages.append(current)
    return messages


def _section_embeds(section: RenderedSection, now: datetime) -> list[dict[str, Any]]:
    color = SECTION_COLORS.get(section.title.lower(), DEFAULT_COLOR)
    if section.cards:
        blocks = [_card_block(card, now) for card in section.cards]
    else:
        body = "\n".join(section.lines).strip()
        blocks = [body] if body else ["(no items)"]

    embeds: list[dict[str, Any]] = []
    current = ""
    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if current and len(candidate) > EMBED_DESCRIPTION_LIMIT:
            embeds.append(_embed(section.title, current, color))
            current = block
        else:
            current = candidate
    if current or not embeds:
        embeds.append(_embed(section.title, current, color))
    return embeds


def _embed(title: str, description: str, color: int) -> dict[str, Any]:
    return {
        "title": title[:EMBED_TITLE_LIMIT],
        "description": description[:EMBED_DESCRIPTION_LIMIT],
        "color": color,
    }


def _card_block(card: SectionCard, now: datetime) -> str:
    if card.url:
        heading = f"**[{_escape_link_text(card.title)}]({card.url})**"
    else:
        heading = f"**{card.title}**"
    lines = [heading]
    if card.summary:
        lines.append(card.summary)
    meta = _meta(card, now)
    if meta:
        lines.append(f"-# {meta}")  # Discord small-subtext markdown
    return "\n".join(lines)


def _meta(card: SectionCard, now: datetime) -> str:
    parts: list[str] = []
    if card.source:
        parts.append(card.source)
    age = _relative_age(card.published_at, now)
    if age:
        parts.append(age)
    return " · ".join(parts)


def _relative_age(published_at: datetime | None, now: datetime) -> str:
    if published_at is None:
        return ""
    seconds = (now - published_at).total_seconds()
    if seconds < 0:
        return ""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _escape_link_text(text: str) -> str:
    # Keep square brackets from breaking the [title](url) markdown link.
    return text.replace("[", "(").replace("]", ")")


def _embed_chars(embed: dict[str, Any]) -> int:
    return len(str(embed.get("title", ""))) + len(str(embed.get("description", "")))
