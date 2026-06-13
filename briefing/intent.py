from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutedIntent:
    profile: str | None = None
    sections: list[str] | None = None
    fallback: str | None = None


FALLBACK_MESSAGE = "I can handle briefing, news, tech, weather, or calendar requests."


def route_mention_text(text: str) -> RoutedIntent:
    normalized = " ".join(text.lower().strip().split())
    if not normalized:
        return RoutedIntent(fallback=FALLBACK_MESSAGE)

    if _contains_any(normalized, ["help", "what can you do", "commands"]):
        return RoutedIntent(fallback=FALLBACK_MESSAGE)

    if "weather" in normalized:
        return RoutedIntent(sections=["weather"])
    if "calendar" in normalized or "schedule" in normalized or "today" in normalized:
        return RoutedIntent(sections=["calendar"])
    if "tech" in normalized:
        return RoutedIntent(sections=["tech"])
    if "news" in normalized:
        return RoutedIntent(sections=["news"])
    if "briefing" in normalized or "brief" in normalized or "morning" in normalized:
        return RoutedIntent(profile="daily")

    return RoutedIntent(fallback=FALLBACK_MESSAGE)


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)
