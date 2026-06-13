from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TextAction = Literal["watch_add", "watch_list", "search_briefings", "search_items"]
FallbackReason = Literal["help", "invalid", "unknown"]


@dataclass(frozen=True)
class RoutedIntent:
    profile: str | None = None
    sections: list[str] | None = None
    text_action: TextAction | None = None
    text_argument: str | None = None
    fallback: str | None = None
    fallback_reason: FallbackReason | None = None


HELP_MESSAGE = """I can handle:
* `/briefing now`, `/briefing news`, `/briefing tech`
* `/briefing profile profile:<name>`
* `/weather`
* `/calendar today`
* `/watch add <term>` and `/watch list`
* `/search briefings <query>` and `/search items <query>`
* `/feeds list` and `/summarize url <url>`

Mention shortcuts:
* `@huginn briefing` or `@huginn briefing <profile>`
* `@huginn news`, `tech`, `weather`, or `calendar`
* `@huginn watch add <term>` or `watch list`
* `@huginn search briefings <query>` or `search items <query>`"""

FALLBACK_MESSAGE = HELP_MESSAGE


DEFAULT_SECTION_NAMES = {"weather", "calendar", "music", "local", "ai", "tech", "news"}


def route_mention_text(
    text: str,
    *,
    profile_names: list[str] | set[str] | None = None,
    section_names: list[str] | set[str] | None = None,
) -> RoutedIntent:
    collapsed = " ".join(text.strip().split())
    normalized = collapsed.lower()
    if not normalized:
        return RoutedIntent(fallback=FALLBACK_MESSAGE, fallback_reason="help")

    if _contains_any(normalized, ["help", "what can you do", "commands"]):
        return RoutedIntent(fallback=FALLBACK_MESSAGE, fallback_reason="help")

    search_intent = _route_search(normalized, collapsed)
    if search_intent:
        return search_intent

    watch_intent = _route_watch(normalized, collapsed)
    if watch_intent:
        return watch_intent

    profile_intent = _route_named_profile(normalized, profile_names or set())
    if profile_intent:
        return profile_intent

    configured_sections = set(section_names or DEFAULT_SECTION_NAMES)
    if "weather" in normalized:
        return RoutedIntent(sections=["weather"])
    if "calendar" in normalized or "schedule" in normalized or "today" in normalized:
        return RoutedIntent(sections=["calendar"])
    section_intent = _route_named_section(normalized, configured_sections)
    if section_intent:
        return section_intent
    if "briefing" in normalized or "brief" in normalized or "morning" in normalized:
        return RoutedIntent(profile="daily")

    return RoutedIntent(fallback=FALLBACK_MESSAGE, fallback_reason="unknown")


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _route_named_profile(normalized: str, profile_names: list[str] | set[str]) -> RoutedIntent | None:
    for profile_name in sorted(profile_names, key=len, reverse=True):
        profile = profile_name.casefold()
        if (
            normalized == profile
            or normalized == f"briefing {profile}"
            or normalized == f"brief {profile}"
            or normalized == f"{profile} briefing"
            or normalized == f"{profile} brief"
            or normalized.startswith(f"briefing {profile} ")
            or normalized.startswith(f"brief {profile} ")
            or normalized.startswith(f"{profile} briefing ")
            or normalized.startswith(f"{profile} brief ")
        ):
            return RoutedIntent(profile=profile_name)
    return None


def _route_named_section(normalized: str, section_names: list[str] | set[str]) -> RoutedIntent | None:
    for section_name in sorted(section_names, key=len, reverse=True):
        section = section_name.casefold()
        if (
            normalized == section
            or normalized == f"{section} briefing"
            or normalized == f"{section} brief"
            or normalized == f"briefing {section}"
            or normalized == f"brief {section}"
            or normalized.startswith(f"{section} ")
        ):
            return RoutedIntent(sections=[section_name])
    return None


def _route_search(normalized: str, original: str) -> RoutedIntent | None:
    if not normalized.startswith("search "):
        return None
    rest_normalized = normalized.removeprefix("search ").strip()
    rest_original = original[len("search ") :].strip()
    if rest_normalized.startswith("briefings "):
        query = rest_original[len("briefings ") :].strip()
        if query:
            return RoutedIntent(text_action="search_briefings", text_argument=query)
    if rest_normalized.startswith("items "):
        query = rest_original[len("items ") :].strip()
        if query:
            return RoutedIntent(text_action="search_items", text_argument=query)
    return RoutedIntent(fallback=FALLBACK_MESSAGE, fallback_reason="invalid")


def _route_watch(normalized: str, original: str) -> RoutedIntent | None:
    if not normalized.startswith("watch "):
        return None
    rest_normalized = normalized.removeprefix("watch ").strip()
    rest_original = original[len("watch ") :].strip()
    if rest_normalized == "list":
        return RoutedIntent(text_action="watch_list")
    if rest_normalized.startswith("add "):
        term = rest_original[len("add ") :].strip()
        if term:
            return RoutedIntent(text_action="watch_add", text_argument=term)
    return RoutedIntent(fallback=FALLBACK_MESSAGE, fallback_reason="invalid")
