from __future__ import annotations

from briefing.config import LlmConfig
from briefing.llm.base import SummaryRequestItem
from briefing.llm.openai_compat import OpenAICompatProvider


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": "  hello from huginn  "}}]}


class FakeJsonResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        content = '{"lede": "", "summaries": [{"item_num": 1, "summary": "ok"}]}'
        return {"choices": [{"message": {"content": content}}]}


def _capture_post(monkeypatch, response):
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr("briefing.llm.openai_compat.httpx.post", fake_post)
    return captured


def test_summarize_requests_json_mode_by_default(monkeypatch) -> None:
    captured = _capture_post(monkeypatch, FakeJsonResponse())
    provider = OpenAICompatProvider(LlmConfig(base_url="http://llm.local/v1", model="m"))

    provider.summarize(
        system_prompt="s",
        items=[SummaryRequestItem(item_num=1, title="t", text="x")],
    )

    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_summarize_omits_json_mode_when_disabled(monkeypatch) -> None:
    captured = _capture_post(monkeypatch, FakeJsonResponse())
    provider = OpenAICompatProvider(
        LlmConfig(base_url="http://llm.local/v1", model="m", json_mode=False)
    )

    provider.summarize(
        system_prompt="s",
        items=[SummaryRequestItem(item_num=1, title="t", text="x")],
    )

    assert "response_format" not in captured["json"]


def test_chat_never_requests_json_mode(monkeypatch) -> None:
    captured = _capture_post(monkeypatch, FakeResponse())
    provider = OpenAICompatProvider(LlmConfig(base_url="http://llm.local/v1", model="m"))

    provider.chat(system_prompt="s", message="hi")

    assert "response_format" not in captured["json"]


def test_openai_compat_chat_uses_plain_text_payload(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("briefing.llm.openai_compat.httpx.post", fake_post)
    provider = OpenAICompatProvider(
        LlmConfig(
            base_url="http://llm.local/v1",
            model="test-model",
            timeout_seconds=12,
        )
    )

    response = provider.chat(
        system_prompt="system",
        message="user message",
        max_tokens=123,
        temperature=0.8,
    )

    assert response == "hello from huginn"
    assert captured["url"] == "http://llm.local/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["max_tokens"] == 123
    assert captured["json"]["temperature"] == 0.8
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user message"},
    ]
