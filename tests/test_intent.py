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


def test_unknown_request_gets_safe_fallback() -> None:
    routed = route_mention_text("do something weird")

    assert routed.fallback == FALLBACK_MESSAGE
