from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from briefing.sections.base import RenderedSection
from briefing.utils.time import utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id            INTEGER PRIMARY KEY,
  dedup_hash    TEXT UNIQUE NOT NULL,
  url           TEXT NOT NULL,
  guid          TEXT,
  title         TEXT NOT NULL,
  source        TEXT NOT NULL,
  published_at  TEXT NOT NULL,
  fetched_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
  id            INTEGER PRIMARY KEY,
  item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  model         TEXT NOT NULL,
  prompt_hash   TEXT NOT NULL,
  summary       TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  UNIQUE(item_id, model, prompt_hash)
);

CREATE TABLE IF NOT EXISTS briefings (
  id            INTEGER PRIMARY KEY,
  profile       TEXT,
  sections      TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  sent          INTEGER DEFAULT 0,
  body          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefing_items (
  briefing_id   INTEGER NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
  item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  section       TEXT NOT NULL,
  PRIMARY KEY (briefing_id, item_id, section)
);

CREATE TABLE IF NOT EXISTS feed_state (
  feed_key      TEXT PRIMARY KEY,
  etag          TEXT,
  last_modified TEXT,
  last_fetched  TEXT,
  last_status   INTEGER
);
"""


@dataclass(frozen=True)
class StoredItem:
    id: int
    dedup_hash: str
    url: str
    guid: str | None
    title: str
    source: str
    published_at: str
    fetched_at: str


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def insert_or_get_item(
        self,
        *,
        dedup_hash: str,
        url: str,
        guid: str | None,
        title: str,
        source: str,
        published_at: str,
        fetched_at: str,
    ) -> StoredItem:
        self.init()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO items
                  (dedup_hash, url, guid, title, source, published_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (dedup_hash, url, guid, title, source, published_at, fetched_at),
            )
            row = connection.execute(
                """
                SELECT id, dedup_hash, url, guid, title, source, published_at, fetched_at
                FROM items
                WHERE dedup_hash = ?
                """,
                (dedup_hash,),
            ).fetchone()
        return _stored_item_from_row(row)

    def get_feed_state(self, feed_key: str) -> dict[str, str | int | None] | None:
        self.init()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT feed_key, etag, last_modified, last_fetched, last_status
                FROM feed_state
                WHERE feed_key = ?
                """,
                (feed_key,),
            ).fetchone()
        return dict(row) if row else None

    def update_feed_state(
        self,
        feed_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
        status: int | None,
    ) -> None:
        self.init()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO feed_state (feed_key, etag, last_modified, last_fetched, last_status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(feed_key) DO UPDATE SET
                  etag = excluded.etag,
                  last_modified = excluded.last_modified,
                  last_fetched = excluded.last_fetched,
                  last_status = excluded.last_status
                """,
                (feed_key, etag, last_modified, utc_now_iso(), status),
            )

    def item_was_used(self, item_id: int) -> bool:
        self.init()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM briefing_items WHERE item_id = ? LIMIT 1",
                (item_id,),
            ).fetchone()
        return row is not None

    def items_for_feed(self, feed_key: str) -> list[StoredItem]:
        self.init()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, dedup_hash, url, guid, title, source, published_at, fetched_at
                FROM items
                WHERE source = ?
                ORDER BY published_at DESC
                """,
                (feed_key,),
            ).fetchall()
        return [_stored_item_from_row(row) for row in rows]

    def get_summary(self, *, item_id: int, model: str, prompt_hash: str) -> str | None:
        self.init()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT summary
                FROM summaries
                WHERE item_id = ? AND model = ? AND prompt_hash = ?
                """,
                (item_id, model, prompt_hash),
            ).fetchone()
        return str(row["summary"]) if row else None

    def save_summary(self, *, item_id: int, model: str, prompt_hash: str, summary: str) -> None:
        self.init()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO summaries (item_id, model, prompt_hash, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (item_id, model, prompt_hash, summary, utc_now_iso()),
            )

    def record_sent_briefing(
        self,
        *,
        profile: str | None,
        section_names: list[str],
        rendered_sections: list[RenderedSection],
        body: str,
    ) -> int:
        self.init()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO briefings (profile, sections, created_at, sent, body)
                VALUES (?, ?, ?, 1, ?)
                """,
                (profile, ",".join(section_names), utc_now_iso(), body),
            )
            briefing_id = int(cursor.lastrowid)
            for rendered in rendered_sections:
                for item_id in rendered.item_ids:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO briefing_items (briefing_id, item_id, section)
                        VALUES (?, ?, ?)
                        """,
                        (briefing_id, item_id, rendered.title.lower()),
                    )
        return briefing_id

    def count_items(self) -> int:
        self.init()
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])

    def count_briefings(self) -> int:
        self.init()
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM briefings").fetchone()[0])

    def feed_states(self, feed_keys: list[str] | None = None) -> list[dict[str, str | int | None]]:
        self.init()
        with self.connect() as connection:
            if feed_keys:
                placeholders = ",".join("?" for _ in feed_keys)
                rows = connection.execute(
                    f"""
                    SELECT feed_key, etag, last_modified, last_fetched, last_status
                    FROM feed_state
                    WHERE feed_key IN ({placeholders})
                    ORDER BY feed_key
                    """,
                    tuple(feed_keys),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT feed_key, etag, last_modified, last_fetched, last_status
                    FROM feed_state
                    ORDER BY feed_key
                    """
                ).fetchall()
        return [dict(row) for row in rows]


def _stored_item_from_row(row: sqlite3.Row) -> StoredItem:
    return StoredItem(
        id=int(row["id"]),
        dedup_hash=str(row["dedup_hash"]),
        url=str(row["url"]),
        guid=row["guid"],
        title=str(row["title"]),
        source=str(row["source"]),
        published_at=str(row["published_at"]),
        fetched_at=str(row["fetched_at"]),
    )
