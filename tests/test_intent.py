from __future__ import annotations

from briefing.intent import FALLBACK_MESSAGE, route_mention_text


def test_route_weather_request() -> None:
    routed = route_mention_text("what's the weather?")

    assert routed.sections == ["weather"]
    assert routed.profile is None
    assert routed.fallback is None


def test_route_calendar_request() -> None:
    routed = route_mention_text("what is on my schedule today")

    assert routed.sections == ["calendar"]


def test_route_briefing_request() -> None:
    routed = route_mention_text("morning briefing please")

    assert routed.profile == "daily"


def test_route_news_and_tech_requests() -> None:
    assert route_mention_text("news please").sections == ["news"]
    assert route_mention_text("tech briefing").sections == ["tech"]


def test_route_additional_briefing_sections() -> None:
    assert route_mention_text("music update").sections == ["music"]
    assert route_mention_text("local news").sections == ["local"]
    assert route_mention_text("ai briefing").sections == ["ai"]


def test_route_configured_profile_names() -> None:
    routed = route_mention_text(
        "briefing music",
        profile_names={"daily", "music", "local", "ai"},
        section_names={"news", "music", "local", "ai"},
    )

    assert routed.profile == "music"
    assert routed.sections is None


def test_route_configured_profile_name_before_briefing_word() -> None:
    routed = route_mention_text(
        "local briefing please",
        profile_names={"daily", "music", "local", "ai"},
        section_names={"news", "music", "local", "ai"},
    )

    assert routed.profile == "local"


def test_route_help_gets_command_help() -> None:
    routed = route_mention_text("help")

    assert routed.fallback == FALLBACK_MESSAGE
    assert "/briefing now" in routed.fallback
    assert "watch add" in routed.fallback


def test_route_watch_requests() -> None:
    add = route_mention_text("watch add Fedora Linux")
    listing = route_mention_text("watch list")

    assert add.text_action == "watch_add"
    assert add.text_argument == "Fedora Linux"
    assert listing.text_action == "watch_list"


def test_route_search_requests() -> None:
    briefings = route_mention_text("search briefings Fedora")
    items = route_mention_text("search items OpenAI")

    assert briefings.text_action == "search_briefings"
    assert briefings.text_argument == "Fedora"
    assert items.text_action == "search_items"
    assert items.text_argument == "OpenAI"


def test_unknown_request_gets_safe_fallback() -> None:
    routed = route_mention_text("do something weird")

    assert routed.fallback == FALLBACK_MESSAGE
