from __future__ import annotations

import logging
import re
from calendar import timegm
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import feedparser
import httpx

from briefing.config import FeedConfig, RssSectionConfig
from briefing.db import Database, StoredItem
from briefing.llm.base import LlmProvider, SummaryRequestItem
from briefing.llm.openai_compat import OpenAICompatProvider
from briefing.llm.prompt import build_system_prompt, llm_enabled_for_section, prompt_hash
from briefing.sections.base import Item, RenderedSection, RunContext, SectionCard
from briefing.utils.article import fetch_article_text
from briefing.utils.hashing import dedup_hash_for_entry
from briefing.utils.time import cutoff_from_hours, parse_duration_hours, to_utc_iso, utc_now

LOG = logging.getLogger(__name__)

USER_AGENT = "morning-briefing-bot/0.1 (+local personal briefing bot)"
FEED_TIMEOUT_SECONDS = 15
SUMMARY_LIMIT = 2000
ARTICLE_TEXT_LIMIT = 6000


@dataclass(frozen=True)
class RssItem(Item):
    id: int = 0
    guid: str | None = None
    dedup_hash: str = ""
    feed_key: str = ""
    feed_priority: int = 0
    published_at: datetime = datetime.min.replace(tzinfo=UTC)


class RssSection:
    def __init__(self, name: str, section_config: RssSectionConfig) -> None:
        self.name = name
        self.section_config = section_config

    def collect(self, context: RunContext) -> list[RssItem]:
        database = Database(context.config.bot.database_path)
        items: list[RssItem] = []
        for feed_key in self.section_config.feeds:
            feed_config = context.config.feeds[feed_key]
            items.extend(self._fetch_feed(feed_key, feed_config, database))
        return items

    def select(self, items: list[RssItem], context: RunContext) -> list[RssItem]:
        since_hours = self.section_config.since_hours
        if context.since:
            since_hours = parse_duration_hours(context.since)
        max_items = context.max_items or self.section_config.max_items
        cutoff = cutoff_from_hours(utc_now(), since_hours)
        database = Database(context.config.bot.database_path)

        deduped: list[RssItem] = []
        seen_candidates: set[tuple[int, str]] = set()
        for item in items:
            candidate_key = (item.id, item.dedup_hash)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            deduped.append(item)

        used = database.used_item_ids([item.id for item in deduped])
        selected = [
            item for item in deduped if item.published_at > cutoff and item.id not in used
        ]
        selected.sort(key=lambda item: (item.feed_priority, item.published_at), reverse=True)
        if self.section_config.max_items_per_feed:
            capped: list[RssItem] = []
            feed_counts: dict[str, int] = {}
            for item in selected:
                feed_count = feed_counts.get(item.feed_key, 0)
                if feed_count >= self.section_config.max_items_per_feed:
                    continue
                capped.append(item)
                feed_counts[item.feed_key] = feed_count + 1
                if len(capped) >= max_items:
                    break
            return capped
        return selected[:max_items]

    def render(self, items: list[RssItem], context: RunContext) -> RenderedSection:
        lines: list[str] = []
        link_lines: list[str] = []
        lede, summaries = self._summaries_for_items(items, context)
        if lede:
            lines.append(lede)
        cards: list[SectionCard] = []
        for item in items:
            summary = summaries.get(item.id)
            if summary:
                lines.append(f"* **{item.title}** - {summary}")
            else:
                lines.append(f"* {item.title}")
            if item.url:
                link_lines.append(item.url)
            cards.append(
                SectionCard(
                    title=item.title,
                    url=item.url,
                    summary=summary,
                    source=item.source,
                    published_at=item.published_at,
                )
            )
        if not lines:
            lines.append("No new items.")
        return RenderedSection(
            title=self.name.title(),
            lines=lines,
            link_lines=link_lines,
            item_ids=[item.id for item in items],
            cards=cards,
        )

    def _summaries_for_items(
        self, items: list[RssItem], context: RunContext
    ) -> tuple[str, dict[int, str]]:
        if not items or not llm_enabled_for_section(context, self.section_config.use_llm):
            return "", {}

        database = Database(context.config.bot.database_path)
        system_prompt = build_system_prompt(context)
        cache_key = prompt_hash(system_prompt)
        model = context.config.llm.model
        summaries: dict[int, str] = {}
        missing: list[RssItem] = []

        for item in items:
            cached = database.get_summary(item_id=item.id, model=model, prompt_hash=cache_key)
            if cached:
                summaries[item.id] = cached
            else:
                missing.append(item)

        if not missing:
            return "", summaries

        try:
            provider = self._build_llm_provider(context)
            request_items = [
                SummaryRequestItem(
                    item_num=index,
                    title=item.title,
                    text=self._summary_source_text(item),
                )
                for index, item in enumerate(missing, start=1)
            ]
            result = provider.summarize(system_prompt=system_prompt, items=request_items)
        except Exception as exc:
            LOG.warning("LLM summaries unavailable for section %s: %s", self.name, exc)
            return "", summaries

        for index, item in enumerate(missing, start=1):
            summary = result.summaries.get(index, "").strip()
            if not summary:
                continue
            summaries[item.id] = summary
            database.save_summary(
                item_id=item.id,
                model=provider.model,
                prompt_hash=cache_key,
                summary=summary,
            )
        return result.lede.strip(), summaries

    def _build_llm_provider(self, context: RunContext) -> LlmProvider:
        return OpenAICompatProvider(context.config.llm)

    def _summary_source_text(self, item: RssItem) -> str:
        # With extract_full_article, summarize the real article body instead of
        # the (often one-sentence) RSS blurb. Falls back to the blurb/title when
        # the fetch yields nothing.
        if self.section_config.extract_full_article and item.url:
            article = fetch_article_text(
                item.url,
                timeout=FEED_TIMEOUT_SECONDS,
                limit=ARTICLE_TEXT_LIMIT,
                user_agent=USER_AGENT,
            )
            if article:
                return article
        return item.body or item.title

    def _fetch_feed(
        self,
        feed_key: str,
        feed_config: FeedConfig,
        database: Database,
    ) -> list[RssItem]:
        headers = {"User-Agent": USER_AGENT}
        state = database.get_feed_state(feed_key)
        if state:
            if state.get("etag"):
                headers["If-None-Match"] = str(state["etag"])
            if state.get("last_modified"):
                headers["If-Modified-Since"] = str(state["last_modified"])

        try:
            response = httpx.get(
                feed_config.url,
                headers=headers,
                timeout=FEED_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            LOG.warning("Feed %s failed: %s", feed_key, exc)
            database.update_feed_state(
                feed_key,
                etag=str((state or {}).get("etag")) if (state or {}).get("etag") else None,
                last_modified=(
                    str((state or {}).get("last_modified"))
                    if (state or {}).get("last_modified")
                    else None
                ),
                status=None,
            )
            return []

        etag = response.headers.get("ETag") or (state or {}).get("etag")
        last_modified = response.headers.get("Last-Modified") or (state or {}).get("last_modified")
        database.update_feed_state(
            feed_key,
            etag=str(etag) if etag else None,
            last_modified=str(last_modified) if last_modified else None,
            status=response.status_code,
        )

        if response.status_code == 304:
            return [
                _from_stored_item(stored, feed_config)
                for stored in database.items_for_feed(feed_key)
            ]
        if response.status_code >= 400:
            LOG.warning("Feed %s returned HTTP %s", feed_key, response.status_code)
            return []

        if _response_looks_like_noaa_alerts(response, feed_config):
            return self._normalize_noaa_alerts(feed_key, feed_config, response, database, fetched_at=utc_now())
        if feed_config.type == "html_links":
            return self._normalize_html_links(feed_key, feed_config, response.text, database, fetched_at=utc_now())

        parsed = feedparser.parse(response.content)
        if getattr(parsed, "bozo", False):
            LOG.warning("Feed %s parsed with warnings: %s", feed_key, parsed.get("bozo_exception"))

        fetched_at = utc_now()
        items: list[RssItem] = []
        for entry in parsed.entries:
            normalized = self._normalize_entry(feed_key, feed_config, entry, fetched_at)
            if normalized:
                stored = database.insert_or_get_item(
                    dedup_hash=normalized.dedup_hash,
                    url=normalized.url or "",
                    guid=normalized.guid,
                    title=normalized.title,
                    source=feed_key,
                    published_at=to_utc_iso(normalized.published_at),
                    fetched_at=to_utc_iso(fetched_at),
                )
                items.append(_with_stored_id(normalized, stored))
        return items

    def _normalize_html_links(
        self,
        feed_key: str,
        feed_config: FeedConfig,
        html: str,
        database: Database,
        fetched_at: datetime,
    ) -> list[RssItem]:
        base_url = feed_config.base_url or feed_config.url
        link_pattern = re.compile(feed_config.link_pattern or r".+")
        parser = _LinkParser()
        parser.feed(html)
        items: list[RssItem] = []
        seen_urls: set[str] = set()
        for href, text in parser.links:
            absolute_url = urljoin(base_url, href)
            path = href if href.startswith("/") else absolute_url
            if absolute_url in seen_urls or not link_pattern.search(path):
                continue
            seen_urls.add(absolute_url)
            title = text.strip() or absolute_url
            if not _entry_matches_filters(
                title=title,
                summary="",
                include_keywords=feed_config.filter_include_keywords,
                exclude_keywords=feed_config.filter_exclude_keywords,
            ):
                continue
            dedup_hash = dedup_hash_for_entry(feed_key=feed_key, guid=absolute_url, url=absolute_url)
            normalized = RssItem(
                id=0,
                title=title,
                body="",
                source=feed_config.name,
                url=absolute_url,
                guid=absolute_url,
                dedup_hash=dedup_hash,
                feed_key=feed_key,
                feed_priority=feed_config.priority,
                published_at=fetched_at,
            )
            stored = database.insert_or_get_item(
                dedup_hash=normalized.dedup_hash,
                url=normalized.url or "",
                guid=normalized.guid,
                title=normalized.title,
                source=feed_key,
                published_at=to_utc_iso(normalized.published_at),
                fetched_at=to_utc_iso(fetched_at),
            )
            items.append(_with_stored_id(normalized, stored))
        return items

    def _normalize_noaa_alerts(
        self,
        feed_key: str,
        feed_config: FeedConfig,
        response: httpx.Response,
        database: Database,
        *,
        fetched_at: datetime,
    ) -> list[RssItem]:
        try:
            features = response.json().get("features", [])
        except ValueError as exc:
            LOG.warning("Feed %s returned invalid NOAA alert JSON: %s", feed_key, exc)
            return []

        items: list[RssItem] = []
        for feature in features:
            properties = feature.get("properties") or {}
            title = str(
                properties.get("headline")
                or properties.get("event")
                or "NOAA weather alert"
            ).strip()
            area = str(properties.get("areaDesc") or "").strip()
            summary = "\n".join(
                part
                for part in [
                    area,
                    str(properties.get("description") or "").strip(),
                    str(properties.get("instruction") or "").strip(),
                ]
                if part
            )
            if not title:
                continue
            if feed_config.filter_area_keywords and not _matches_any_keyword(
                area,
                feed_config.filter_area_keywords,
            ):
                continue
            if not _entry_matches_filters(
                title=title,
                summary=summary,
                include_keywords=feed_config.filter_include_keywords,
                exclude_keywords=feed_config.filter_exclude_keywords,
            ):
                continue
            url = str(properties.get("@id") or properties.get("id") or feature.get("id") or "").strip()
            guid = str(properties.get("id") or feature.get("id") or url or title).strip()
            published_at = _datetime_from_noaa_properties(properties, fetched_at)
            dedup_hash = dedup_hash_for_entry(feed_key=feed_key, guid=guid, url=url or guid)
            normalized = RssItem(
                id=0,
                title=title,
                body=summary[:SUMMARY_LIMIT],
                source=feed_config.name,
                url=url,
                guid=guid,
                dedup_hash=dedup_hash,
                feed_key=feed_key,
                feed_priority=feed_config.priority,
                published_at=published_at,
            )
            stored = database.insert_or_get_item(
                dedup_hash=normalized.dedup_hash,
                url=normalized.url or "",
                guid=normalized.guid,
                title=normalized.title,
                source=feed_key,
                published_at=to_utc_iso(normalized.published_at),
                fetched_at=to_utc_iso(fetched_at),
            )
            items.append(_with_stored_id(normalized, stored))
        return items

    def _normalize_entry(
        self,
        feed_key: str,
        feed_config: FeedConfig,
        entry: Any,
        fetched_at: datetime,
    ) -> RssItem | None:
        title = str(entry.get("title", "")).strip()
        url = str(entry.get("link", "")).strip()
        if not title or not url:
            return None

        guid = _entry_guid(entry)
        published_at = _entry_datetime(entry, fetched_at)
        summary = _entry_summary(entry)
        if not _entry_matches_filters(
            title=title,
            summary=summary,
            include_keywords=feed_config.filter_include_keywords,
            exclude_keywords=feed_config.filter_exclude_keywords,
        ):
            return None
        dedup_hash = dedup_hash_for_entry(feed_key=feed_key, guid=guid, url=url)
        return RssItem(
            id=0,
            title=title,
            body=summary[:SUMMARY_LIMIT],
            source=feed_config.name,
            url=url,
            guid=guid,
            dedup_hash=dedup_hash,
            feed_key=feed_key,
            feed_priority=feed_config.priority,
            published_at=published_at,
        )


def _with_stored_id(item: RssItem, stored: StoredItem) -> RssItem:
    return RssItem(
        id=stored.id,
        title=stored.title,
        body=item.body,
        source=item.source,
        url=stored.url,
        guid=stored.guid,
        dedup_hash=stored.dedup_hash,
        feed_key=item.feed_key,
        feed_priority=item.feed_priority,
        published_at=datetime.fromisoformat(stored.published_at),
    )


def _from_stored_item(stored: StoredItem, feed_config: FeedConfig) -> RssItem:
    return RssItem(
        id=stored.id,
        title=stored.title,
        source=feed_config.name,
        url=stored.url,
        guid=stored.guid,
        dedup_hash=stored.dedup_hash,
        feed_key=stored.source,
        feed_priority=feed_config.priority,
        published_at=datetime.fromisoformat(stored.published_at),
    )


def _entry_guid(entry: Any) -> str | None:
    for key in ("id", "guid"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    return None


def _entry_summary(entry: Any) -> str:
    for key in ("summary", "description"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    return ""


def _entry_matches_filters(
    *,
    title: str,
    summary: str,
    include_keywords: list[str],
    exclude_keywords: list[str],
) -> bool:
    haystack = f"{title}\n{summary}".casefold()
    if include_keywords and not any(keyword.casefold() in haystack for keyword in include_keywords):
        return False
    if exclude_keywords and any(keyword.casefold() in haystack for keyword in exclude_keywords):
        return False
    return True


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    haystack = text.casefold()
    return any(keyword.casefold() in haystack for keyword in keywords)


def _response_looks_like_noaa_alerts(response: httpx.Response, feed_config: FeedConfig) -> bool:
    if feed_config.type == "noaa_alerts":
        return True
    content_type = response.headers.get("Content-Type", "")
    return "api.weather.gov/alerts" in feed_config.url and "json" in content_type


def _datetime_from_noaa_properties(properties: dict[str, Any], fallback: datetime) -> datetime:
    for key in ("effective", "sent", "onset"):
        value = properties.get(key)
        if value:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
    return fallback


def _entry_datetime(entry: Any, fallback: datetime) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(timegm(parsed), tz=UTC)

    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            value = parsedate_to_datetime(str(raw))
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            LOG.warning("Could not parse feed timestamp: %r", raw)

    return fallback


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href_stack: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href_stack.append(href)
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href_stack:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        text = " ".join("".join(self._text_parts).split())
        self.links.append((href, text))
        self._text_parts = []
