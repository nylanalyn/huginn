from __future__ import annotations

from briefing.config import AppConfig
from briefing.llm.openai_compat import OpenAICompatProvider
from briefing.utils.article import extract_text
from briefing.utils.net import assert_public_http_url, get_public_url

URL_FETCH_TIMEOUT_SECONDS = 20
URL_TEXT_LIMIT = 12000
FALLBACK_SENTENCE_LIMIT = 5


def feeds_list_text(config: AppConfig) -> str:
    if not config.feeds:
        return "No feeds configured."
    lines = []
    for key, feed in sorted(config.feeds.items()):
        lines.append(f"* {key}: {feed.name} (priority={feed.priority}) - {feed.url}")
    return "\n".join(lines)


def summarize_url_text(config: AppConfig, url: str) -> str:
    # SSRF guard: validates scheme and that the host (and every redirect hop)
    # resolves to a public address before any request is made.
    assert_public_http_url(url)
    if not config.llm.enabled:
        raise ValueError("LLM summaries are disabled in config")

    response = get_public_url(
        url,
        headers={"User-Agent": "morning-briefing-bot/0.1 (+local personal briefing bot)"},
        timeout=URL_FETCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = extract_text(response)
    if not text:
        raise ValueError("No readable text found at URL")

    provider = OpenAICompatProvider(config.llm)
    summary = _llm_summarize(provider, config, url, text)
    if not summary:
        return _extractive_summary(url, text)
    return summary


def _llm_summarize(
    provider: OpenAICompatProvider,
    config: AppConfig,
    url: str,
    text: str,
) -> str:
    article_text = text[:URL_TEXT_LIMIT]
    prompts = [
        (
            "Summarize the user-provided article text. Be concise and factual. "
            "Do not invent details. Include 3-5 bullets and a one-sentence why-it-matters line.",
            f"URL: {url}\n\nArticle text:\n{article_text}",
        ),
        (
            "Write a concise factual summary of the supplied text. If the text is incomplete, summarize only what is present.",
            f"Summarize this page from {url} in 4 bullets:\n\n{article_text[:8000]}",
        ),
    ]
    for system_prompt, message in prompts:
        summary = provider.chat(
            system_prompt=system_prompt,
            message=message,
            max_tokens=min(config.llm.max_tokens, 600),
            temperature=config.llm.temperature,
        ).strip()
        if summary:
            return summary
    return ""


def _extractive_summary(url: str, text: str) -> str:
    sentences = _sentences(text)
    excerpt = " ".join(sentences[:FALLBACK_SENTENCE_LIMIT]).strip()
    if not excerpt:
        raise ValueError("No readable text found at URL")
    return (
        "LLM summary was empty; showing an extractive fallback.\n\n"
        f"Source: {url}\n\n"
        f"{excerpt}"
    )


def _sentences(text: str) -> list[str]:
    collapsed = " ".join(text.split())
    if not collapsed:
        return []
    sentences: list[str] = []
    start = 0
    for index, char in enumerate(collapsed):
        if char not in ".!?":
            continue
        end = index + 1
        sentence = collapsed[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
        if len(sentences) >= FALLBACK_SENTENCE_LIMIT:
            break
    if not sentences:
        return [collapsed[:1000].rstrip()]
    return sentences


