from __future__ import annotations

import json
import logging
import re
from typing import Any

from briefing.llm.base import SummaryResult

LOG = logging.getLogger(__name__)

DEFAULT_SUMMARY_CHAR_LIMIT = 400


def parse_summary_response(
    raw_response: str,
    *,
    item_count: int,
    summary_char_limit: int = DEFAULT_SUMMARY_CHAR_LIMIT,
) -> SummaryResult | None:
    cleaned = strip_code_fences(raw_response).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        LOG.warning("LLM summary response was not valid JSON: %s", exc)
        return None

    if not isinstance(payload, dict):
        LOG.warning("LLM summary response was not an object")
        return None

    lede = payload.get("lede", "")
    lede = lede.strip() if isinstance(lede, str) else ""
    summaries: dict[int, str] = {}
    raw_summaries = payload.get("summaries", [])
    if not isinstance(raw_summaries, list):
        raw_summaries = []

    for raw_item in raw_summaries:
        parsed = _parse_summary_item(raw_item, item_count, summary_char_limit)
        if parsed is not None:
            item_num, summary = parsed
            summaries[item_num] = summary
    return SummaryResult(lede=truncate_at_sentence(lede, summary_char_limit), summaries=summaries)


def strip_code_fences(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text


def truncate_at_sentence(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    clipped = text[:limit].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end >= max(0, limit // 2):
        return clipped[: sentence_end + 1]
    return clipped.rstrip(" ,;:") + "..."


def _parse_summary_item(
    raw_item: Any,
    item_count: int,
    summary_char_limit: int,
) -> tuple[int, str] | None:
    if not isinstance(raw_item, dict):
        return None
    try:
        item_num = int(raw_item.get("item_num"))
    except (TypeError, ValueError):
        return None
    if item_num < 1 or item_num > item_count:
        return None
    summary = raw_item.get("summary", "")
    if not isinstance(summary, str) or not summary.strip():
        LOG.warning("LLM summary missing for item %s", item_num)
        return None
    return item_num, truncate_at_sentence(summary, summary_char_limit)
