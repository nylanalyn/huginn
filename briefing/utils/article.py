from __future__ import annotations

import logging
from html.parser import HTMLParser

import httpx

from briefing.utils.net import UnsafeUrlError, get_public_url

LOG = logging.getLogger(__name__)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self._parts.append(cleaned)

    def text(self) -> str:
        return " ".join(self._parts)


def extract_text(response: httpx.Response) -> str:
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.casefold():
        return " ".join(response.text.split())
    parser = _TextParser()
    parser.feed(response.text)
    return parser.text()


def fetch_article_text(
    url: str,
    *,
    timeout: float,
    limit: int,
    user_agent: str,
) -> str:
    """Best-effort fetch + readable-text extraction for an article URL.

    Returns "" on any failure (bad URL, SSRF block, network error, non-2xx) so
    callers can fall back to whatever text they already have. Goes through the
    SSRF guard because article links come from third-party feed content.
    """
    try:
        response = get_public_url(url, headers={"User-Agent": user_agent}, timeout=timeout)
        response.raise_for_status()
    except (httpx.HTTPError, UnsafeUrlError) as exc:
        LOG.debug("Could not fetch article %s: %s", url, exc)
        return ""
    return extract_text(response)[:limit]
