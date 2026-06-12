from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "at_")) and key.lower() not in TRACKING_PARAMS
    ]
    normalized_query = urlencode(query, doseq=True)
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, normalized_query, ""))


def looks_like_url(value: str | None) -> bool:
    if not value:
        return False
    parts = urlsplit(value.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def dedup_hash_for_entry(*, feed_key: str, guid: str | None, url: str) -> str:
    if looks_like_url(guid):
        return sha256_text(normalize_url(str(guid)))
    if guid:
        return sha256_text(f"{feed_key}:{guid}")
    return sha256_text(normalize_url(url))
