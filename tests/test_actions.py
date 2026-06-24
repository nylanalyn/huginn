from __future__ import annotations

import httpx

from briefing.actions import feeds_list_text, summarize_url_text
from briefing.config import load_config


def test_feeds_list_text_formats_configured_feeds(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [feeds.alpha]
        name = "Alpha Feed"
        url = "https://example.com/feed.xml"
        priority = 7
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    assert feeds_list_text(config) == (
        "* alpha: Alpha Feed (priority=7) - https://example.com/feed.xml"
    )


def test_summarize_url_rejects_non_http_urls(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    config = load_config(config_path)

    try:
        summarize_url_text(config, "file:///tmp/story.txt")
    except ValueError as exc:
        assert "absolute http or https URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_url_fetches_text_and_calls_llm(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        base_url = "http://llm.local/v1"
        model = "test-model"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    calls = {}

    def fake_get(url, **kwargs):
        calls["get"] = {"url": url, **kwargs}
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            headers={"Content-Type": "text/html"},
            text="<html><script>ignore()</script><body><h1>Title</h1><p>Useful article text.</p></body></html>",
        )

    def fake_post(url, json, timeout):
        calls["post"] = {"url": url, "json": json, "timeout": timeout}
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "Useful summary"}}]},
        )

    monkeypatch.setattr("briefing.utils.net.resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr("briefing.utils.net.httpx.get", fake_get)
    monkeypatch.setattr("briefing.llm.openai_compat.httpx.post", fake_post)

    assert summarize_url_text(config, "https://example.com/story") == "Useful summary"
    assert calls["get"]["url"] == "https://example.com/story"
    assert "Useful article text." in calls["post"]["json"]["messages"][1]["content"]
    assert "ignore()" not in calls["post"]["json"]["messages"][1]["content"]


def test_summarize_url_retries_empty_llm_response(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        base_url = "http://llm.local/v1"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    def fake_get(url, **kwargs):
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            headers={"Content-Type": "text/plain"},
            text="Useful article text.",
        )

    post_calls = []

    def fake_post(url, json, timeout):
        del json, timeout
        post_calls.append(url)
        content = "   " if len(post_calls) == 1 else "Retry summary"
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": content}}]},
        )

    monkeypatch.setattr("briefing.utils.net.resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr("briefing.utils.net.httpx.get", fake_get)
    monkeypatch.setattr("briefing.llm.openai_compat.httpx.post", fake_post)

    assert summarize_url_text(config, "https://example.com/story") == "Retry summary"
    assert len(post_calls) == 2


def test_summarize_url_falls_back_when_llm_stays_empty(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        base_url = "http://llm.local/v1"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    def fake_get(url, **kwargs):
        del kwargs
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            headers={"Content-Type": "text/plain"},
            text="First useful sentence. Second useful sentence. Third useful sentence.",
        )

    def fake_post(url, json, timeout):
        del json, timeout
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "   "}}]},
        )

    monkeypatch.setattr("briefing.utils.net.resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr("briefing.utils.net.httpx.get", fake_get)
    monkeypatch.setattr("briefing.llm.openai_compat.httpx.post", fake_post)

    result = summarize_url_text(config, "https://example.com/story")

    assert "LLM summary was empty" in result
    assert "First useful sentence." in result


def test_summarize_url_blocks_private_host(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    config = load_config(config_path)

    monkeypatch.setattr("briefing.utils.net.resolve_host_ips", lambda host, port: ["169.254.169.254"])

    def fail_get(*args, **kwargs):
        raise AssertionError("must not fetch a private host")

    monkeypatch.setattr("briefing.utils.net.httpx.get", fail_get)

    try:
        summarize_url_text(config, "http://metadata.internal/latest/meta-data/")
    except ValueError as exc:
        assert "non-public address" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_url_blocks_redirect_to_private_host(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [llm]
        base_url = "http://llm.local/v1"
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)

    def resolver(host, port):
        return ["10.0.0.5"] if host == "internal.example" else ["93.184.216.34"]

    def fake_get(url, **kwargs):
        assert kwargs.get("follow_redirects") is False
        return httpx.Response(
            302,
            request=httpx.Request("GET", url),
            headers={"Location": "http://internal.example/secret"},
        )

    monkeypatch.setattr("briefing.utils.net.resolve_host_ips", resolver)
    monkeypatch.setattr("briefing.utils.net.httpx.get", fake_get)

    try:
        summarize_url_text(config, "https://public.example/story")
    except ValueError as exc:
        assert "non-public address" in str(exc)
    else:
        raise AssertionError("expected ValueError")
