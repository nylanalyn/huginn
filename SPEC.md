# SPEC.md: Local Morning Briefing Bot

## Project Summary

Build a lightweight, local-first Discord bot whose first feature is scheduled morning briefings. Briefings are assembled by deterministic code — weather, calendar, RSS fetching, filtering, deduplication, scheduling, and Discord delivery are all plain Python. A local LLM is optionally used for bounded language tasks: writing summary prose for news items the code hands it, and later answering direct Discord mentions in a configurable persona (SOUL.md-style).

The long-term shape is a small personal bot the owner fully controls, where briefings are the first section type and future features (email checks, watch lists, interactive commands) are added as new sections and commands on the same core. The scheduled webhook briefing ships first; the persistent interactive bot comes later but is the eventual main body.

## Goals

* Run locally on a Linux server or VPS.
* Use Python 3.11+ inside a virtual environment.
* Send scheduled Discord briefings via webhook.
* Support selectable briefing sections through CLI flags and named profiles.
* Different profiles on different days (daily news vs. tech vs. weekend) via separate systemd timers.
* Use local models where practical; keep working when the LLM is unavailable.
* Give the LLM a configurable personality via a persona file, without compromising factual integrity.
* Store state in SQLite to avoid repeating stories.
* Be simple, inspectable, and easy to extend.

## Non-Goals

* No general autonomous agent.
* No LLM involvement in weather or calendar data.
* No autonomous Discord actions: the chat feature answers direct user messages only.
* No OpenClaw dependency.
* No headless browser.
* No hallucinated news: RSS/feed data is the sole source of truth, enforced structurally (see LLM Behavior).
* One failed feed, API, or model call must never fail the whole briefing.

## Stack

* Python 3.11+ (`tomllib` is in the stdlib — no TOML dependency needed)
* venv or uv-managed virtual environment
* SQLite (stdlib `sqlite3`)
* feedparser
* httpx
* pydantic (config validation)
* typer or argparse
* python-dotenv
* icalendar (calendar parsing)
* trafilatura — optional, article extraction
* Discord webhook for scheduled posts
* discord.py — later, interactive bot mode
* Any OpenAI-compatible chat completions endpoint for the LLM (covers Ollama, llama-server/llama.cpp, and others with one provider implementation)
* systemd service + timer

## Repository Layout

```
morning-briefing-bot/
  README.md
  SPEC.md
  pyproject.toml
  .env.example
  config.example.toml
  personas/
    default.md
    example-terse.md
  briefing/
    __init__.py
    main.py
    config.py
    cli.py
    db.py
    discord_webhook.py
    sections/
      __init__.py
      base.py
      ping.py
      weather.py
      calendar.py
      rss.py
    llm/
      __init__.py
      base.py
      openai_compat.py
      null.py
    render/
      __init__.py
      discord.py
      text.py
    utils/
      logging.py
      time.py
      hashing.py
  tests/
    test_config.py
    test_rss.py
    test_selection.py
    test_render.py
    test_persona.py
```

## Configuration

Configuration lives in `config.toml`. Secrets live in environment variables (loaded from `.env`).

**Validation requirement:** config is parsed into pydantic models at startup. Any profile referencing an undefined section, or any section referencing an undefined feed, is a hard startup error with a clear message. Unknown keys warn. The example config below must validate against the shipped code — keeping `config.example.toml` valid is part of every stage's Definition of Done.

```toml
[bot]
timezone = "America/New_York"
database_path = "briefing.sqlite3"

[discord]
webhook_url_env = "DISCORD_WEBHOOK_URL"

# Interactive bot mode (Stage 7) — shape defined now so Stage 0
# validation covers it; ignored until the bot service exists.
[discord.interactive]
enabled = false
token_env = "DISCORD_BOT_TOKEN"
allowed_guild_ids = [123456789]
allowed_channel_ids = [987654321]
allowed_user_ids = []     # empty = anyone in the allowed guild/channels
mention_chat_enabled = false
mention_chat_max_tokens = 500
mention_chat_temperature = 0.7

[llm]
enabled = true
# Any OpenAI-compatible endpoint: Ollama (http://localhost:11434/v1),
# llama-server (http://localhost:8080/v1), etc.
base_url = "http://localhost:11434/v1"
model = "llama3.1:8b"
temperature = 0.2
timeout_seconds = 60
persona_path = "personas/default.md"

[profiles.daily]
sections = ["weather", "calendar", "news"]

[profiles.tech]
sections = ["weather", "calendar", "tech"]
# Optional per-profile persona override:
# persona_path = "personas/example-terse.md"

[sections.weather]
type = "weather"
enabled = true
provider = "open-meteo"
latitude = 40.7128
longitude = -74.0060
units = "imperial"        # or "metric"

[sections.calendar]
type = "calendar"
enabled = true
source = "json"           # "json" | "ics_url" | "caldav"
# source = "json":
json_path = "calendar.json"
# source = "ics_url" (e.g. a Proton Calendar share link — treat as a secret):
# ics_url_env = "CALENDAR_ICS_URL"
# source = "caldav" (e.g. self-hosted Radicale):
# caldav_url_env = "CALDAV_URL"
# caldav_user_env = "CALDAV_USER"
# caldav_pass_env = "CALDAV_PASS"
lookahead_hours = 24

[sections.news]
type = "rss"
enabled = true
use_llm = true
max_items = 8
since_hours = 24
extract_full_article = false   # true = fetch + trafilatura when summarizing
feeds = ["npr", "ap"]

[sections.tech]
type = "rss"
enabled = true
use_llm = true
max_items = 8
since_hours = 24
feeds = ["ars", "lobsters"]

[feeds.npr]
name = "NPR News"
url = "https://feeds.npr.org/1001/rss.xml"
priority = 8

[feeds.ap]
name = "AP Top News"
url = "https://rsshub.app/ap/topics/apf-topnews"
priority = 9

[feeds.ars]
name = "Ars Technica"
url = "https://feeds.arstechnica.com/arstechnica/index"
priority = 8

[feeds.lobsters]
name = "Lobsters"
url = "https://lobste.rs/rss"
priority = 6
```

Every feed referenced by a section is defined above. Profiles only reference defined sections. (Feed URLs in the example must be verified working at implementation time and replaced if dead.)

## Persona System (SOUL.md-style)

The persona file gives the LLM's briefing prose a consistent voice or character. It is plain Markdown, written by the user, loaded at runtime, and injected into the LLM system prompt.

Rules:

* `persona_path` in `[llm]` sets the default persona; a profile may override it with its own `persona_path` (the Friday briefing can have a different personality than the Monday one).
* The persona controls **voice only** — tone, word choice, attitude, sign-off style. It is concatenated into the system prompt *after* the non-negotiable factual instructions, and the system prompt explicitly states that factual constraints override persona instructions.
* The persona file cannot grant capabilities: regardless of persona content, summary generation is still limited to prose for the items it is given, and mention chat can only answer the direct user message with the context provided (see LLM Behavior). A persona that says "make up exciting news" has no mechanism to alter briefing titles, sources, or links because the renderer attaches those deterministically.
* If the persona file is missing or unreadable: log a warning, proceed with a neutral built-in voice. Never fail the briefing over a persona.
* The null provider and `--no-llm` mode ignore personas entirely — fallback output is plain titles/sources/links with no voice.
* Keep personas short (a few hundred words). The repo ships `personas/default.md` (neutral, concise) and one example with obvious character, as templates.

Example `personas/default.md`:

```markdown
# Briefing Voice

You write like a sharp, dry morning radio host who respects the
listener's time. Short sentences. No filler, no "in today's
fast-paced world." One wry aside per briefing, maximum. When a
story is grim, be plain about it — no forced levity.
```

## CLI Requirements

```
briefing run --profile daily
briefing run --sections weather,calendar,news
briefing run --sections tech --since 12h
briefing run --sections news --no-llm
briefing run --sections news --send
briefing run --profile daily --persona personas/example-terse.md
briefing feeds list
briefing db init
briefing db status
briefing db prune --older-than 90d
briefing health
```

`briefing health` checks database connectivity, summarizes feed state (last fetch/status per feed), and pings the LLM endpoint if enabled — nonzero exit on failure, suitable for monitoring.

The `ping` section is a built-in requiring no configuration; `--sections ping` always works.

Required flags for `run`:

* `--profile`
* `--sections`
* `--since`
* `--max-items`
* `--no-llm`
* `--dry-run`
* `--send`
* `--persona` (path override, highest precedence)
* `--format text|discord`

**Default behavior: dry-run.** `briefing run` with neither flag prints the briefing to stdout and sends nothing. Sending requires explicit `--send`. `--dry-run --send` together is an error. This makes the safe path the default and matches the systemd unit, which passes `--send` explicitly.

## Core Architecture

Each briefing section implements a shared interface:

```python
class BriefingSection:
    name: str

    def collect(self, context) -> list[Item]: ...
    def select(self, items: list[Item], context) -> list[Item]: ...
    def render(self, items: list[Item], context) -> RenderedSection: ...
```

* All RSS-backed sections (news, tech, and any future categories) use one `RssSection` implementation parameterized by config.
* Weather and calendar are dedicated deterministic providers. The calendar section dispatches on `source` (`json` / `ics_url` / `caldav`) so the backend can change without touching the rest of the bot. Start with `json`; `ics_url` covers a Proton Calendar share link; `caldav` covers self-hosted Radicale.

  The `json` backend reads this format:

  ```json
  {
    "events": [
      {
        "summary": "Standup",
        "start": "2026-06-11T09:00:00-04:00",
        "end": "2026-06-11T09:30:00-04:00",
        "location": "Zoom"
      },
      {
        "summary": "Trash day",
        "start": "2026-06-12",
        "all_day": true
      }
    ]
  }
  ```

  `summary` and `start` are required. `end` omitted means a point-in-time event. `all_day: true` with a date-only `start` renders without a time. `location` is optional. Timestamps may carry offsets; date-only values are interpreted in the configured `[bot] timezone`.
* A trivial `ping` section exists for end-to-end testing of delivery (used in Stage 1).
* Section failures are isolated: a section that raises is logged and replaced by a one-line error notice in the briefing; the rest of the briefing proceeds.

### Item Selection Algorithm (RSS)

Defined precisely so "priority" means something:

1. Fetch all configured feeds for the section (conditional requests — see Feed Fetching).
2. Normalize entries to `Item` (see Timestamps).
3. Drop items older than `since_hours` (or `--since`).
4. Drop items already seen (dedup key below).
5. Sort by `(feed priority DESC, published_at DESC)`.
6. Truncate to `max_items` (or `--max-items`).
7. Mark selected items as used via the `briefing_items` junction table after a successful send.

**Dedup key rules:**

* If the entry's GUID is itself a URL (the common `isPermaLink="true"` case): use it, normalized, hashed **globally** — so the same story syndicated into multiple feeds dedupes to one item (this is desired behavior, not a bug).
* If the GUID is an opaque token (bare integer, internal ID): hash `feed_key:guid` — opaque GUIDs are only unique within their feed, and scoping prevents accidental collisions across feeds.
* If there is no GUID: use the entry URL, normalized, hashed globally.

URL normalization: strip known tracking parameters (`utm_*`, `fbclid`, `gclid`, etc.), lowercase the host, remove fragments. The SHA-256 of the resulting key is `dedup_hash`, the sole uniqueness constraint.

**`--since` semantics:** `--since` on the CLI overrides the section's `since_hours` for that run. Either way, the cutoff is a simple instant: an item is in-window when `published_at > now - window`. A 24-hour briefing run at 07:00 includes items published since 07:00 the previous day — not since midnight.

### Feed Fetching

* Store per-feed `ETag` and `Last-Modified`; send `If-None-Match` / `If-Modified-Since` on every fetch. A 304 is a successful no-op.
* Per-feed timeout (default 15s). A timed-out or erroring feed is logged and skipped; the section continues with remaining feeds.
* Honest User-Agent string identifying the bot.
* Feeds are fetched sequentially; with a typical handful of feeds this is fast and inherently polite, and `RandomizedDelaySec` in the timer already de-synchronizes the run from everyone else's top-of-the-hour cron. If fetching ever goes concurrent, add a concurrency cap — not random sleeps.

### Article Text for Summarization

The text handed to the LLM per item is sourced by rule:

1. If the feed entry has a `summary`/`description`: use it (truncated to a sane length, e.g. 2,000 chars).
2. If it doesn't, **or** the section sets `extract_full_article = true`: fetch the article URL and extract readable text with trafilatura (per-article timeout, default 10s; extraction failure falls back to title only).

Full-article extraction is off by default — feed summaries are usually enough for a one-to-two-sentence briefing item, and skipping the extra fetches keeps the run fast.

### Timestamps

All stored timestamps are ISO 8601 in UTC. Feed-provided dates are normalized to UTC at ingest (feedparser's parsed structs → aware datetimes; missing dates fall back to fetch time, flagged). `--since` and `since_hours` are evaluated as instants; rendering converts to the configured `[bot] timezone`.

## Database Schema

```sql
CREATE TABLE items (
  id            INTEGER PRIMARY KEY,
  dedup_hash    TEXT UNIQUE NOT NULL,   -- sha256 of GUID or normalized URL
  url           TEXT NOT NULL,          -- original URL, for display/links
  guid          TEXT,
  title         TEXT NOT NULL,
  source        TEXT NOT NULL,          -- feed key
  published_at  TEXT NOT NULL,          -- ISO 8601 UTC
  fetched_at    TEXT NOT NULL           -- ISO 8601 UTC
);

CREATE TABLE summaries (
  id            INTEGER PRIMARY KEY,
  item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  model         TEXT NOT NULL,
  prompt_hash   TEXT NOT NULL,          -- sha256 of (system prompt + persona)
  summary       TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  UNIQUE(item_id, model, prompt_hash)
);

CREATE TABLE briefings (
  id            INTEGER PRIMARY KEY,
  profile       TEXT,
  sections      TEXT NOT NULL,          -- comma-separated
  created_at    TEXT NOT NULL,
  sent          INTEGER DEFAULT 0,
  body          TEXT NOT NULL
);

CREATE TABLE briefing_items (
  briefing_id   INTEGER NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
  item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  section       TEXT NOT NULL,
  PRIMARY KEY (briefing_id, item_id, section)
);

CREATE TABLE feed_state (
  feed_key      TEXT PRIMARY KEY,
  etag          TEXT,
  last_modified TEXT,
  last_fetched  TEXT,
  last_status   INTEGER
);
```

Notes:

* `dedup_hash` is the single uniqueness constraint on items (no redundant unique URL column).
* Items carry no section/category column — section membership lives only in `briefing_items`, since a story can legitimately appear in multiple sections (an AI story in both `news` and `tech`) and history stays queryable (useful for Stage 10 search).
* **Every connection must execute `PRAGMA foreign_keys = ON`** — SQLite ignores foreign key constraints by default, and without this the `ON DELETE CASCADE` clauses are decorative.
* Summaries are cached keyed by `(item, model, prompt_hash)`, so changing models or editing a persona invalidates the cache naturally instead of serving stale voice/content.
* `briefing db prune --older-than 90d` deletes old items and briefings; their summaries and `briefing_items` rows go with them via CASCADE. The database does not grow unbounded.
* All writes are idempotent (`INSERT OR IGNORE` on dedup-keyed inserts).

## LLM Behavior

The LLM is optional and replaceable.

There are two LLM use cases, with separate prompts and response handling:

* **Briefing summaries:** structured JSON prose for selected RSS items only.
* **Mention chat:** plain-text replies to direct Discord mentions, using the configured persona.

Briefing-summary constraints are stricter because those responses sit beside real news items.

**Structural constraint (the anti-hallucination mechanism):** the LLM never emits URLs, source names, or story titles into the briefing. The code hands it a numbered list of selected items (title + feed summary/extracted text) and receives back summary prose per item number, plus optionally a short section lede. The renderer then deterministically attaches the real title, source, and link to each summary. A made-up story has nowhere to go; a wrong link is impossible. This also means the `--no-llm` fallback (plain title/source/link) is the same render path with empty prose.

If enabled, the LLM may:

* Write one-to-two-sentence summaries per item.
* Group related items and note the connection.
* Write brief "why it matters" notes.
* Apply the persona voice consistently.

It must not (and structurally cannot, per above):

* Introduce stories not in the selected set.
* Alter titles, sources, or links.
* Touch weather or calendar output.
* Browse or fetch anything.
* Override deterministic filtering or selection.

System prompt assembly order: (1) factual constraints and output format, (2) persona file contents, (3) explicit note that (1) overrides (2) on any conflict.

### Prompt/Response Contract

The exchange format is pinned, because "returns JSON" is aspirational with 8B-class local models and the parser must be defensive.

Request (user message), after the assembled system prompt:

```
You have 3 news items. Respond with ONLY a JSON object, no markdown
fences, no preamble, in this shape:

{
  "lede": "optional 1-2 sentence section opener, or empty string",
  "summaries": [
    {"item_num": 1, "summary": "..."},
    {"item_num": 2, "summary": "..."},
    {"item_num": 3, "summary": "..."}
  ]
}

Items:
1. Title: Fed Raises Rates
   Text: The Federal Reserve raised interest rates by 25 basis points...

2. Title: New Local Model Released
   Text: A new 8B open-weights model was announced...

3. Title: Weather Anomaly Detected
   Text: Scientists observed...
```

(Note: item titles are shown to the LLM for context, but the renderer ignores everything except `lede` and the `summary` strings — titles, sources, and links in the output always come from the database.)

Response handling — per-item degradation, never all-or-nothing:

* Strip markdown code fences before parsing (local models add them no matter what you say).
* Parse failure for the whole response → log, plain fallback for the entire section.
* Parse succeeds but an `item_num` is missing or its summary is empty → that item renders plain (title/source/link only), logged as a warning; the rest keep their summaries.
* `item_num` values outside the given range are ignored.
* A summary longer than a configured cap (default 400 chars) is truncated at a sentence boundary.

Failure handling: timeout, connection error, or malformed output → log, fall back to plain rendering for that section. The briefing always ships.

### Mention Chat Contract

Mention chat is intentionally small at first. When an allowed Discord user mentions the bot and the message is not recognized as a briefing/weather/calendar/help command, the bot may send the remaining text to the local LLM and reply in-channel.

System prompt assembly order for mention chat:

1. Chat behavior constraints.
2. Persona file contents.
3. Explicit note that behavior constraints override persona text on conflict.

The chat constraints are:

* You are Huginn, a private Discord bot for the user.
* Respond naturally in the configured persona.
* Be concise unless the user asks for depth.
* Do not claim to have checked live data, Discord history, files, feeds, weather, calendar, or the internet unless that context was explicitly provided in the prompt.
* If the user asks for a briefing, news, tech, weather, calendar, search, watch-list management, or help, those are application commands and should be handled by deterministic routing before chat.
* Do not invent personal memories. Stateless mention chat has no memory beyond the current message.

Response handling:

* Plain text only; no JSON contract.
* Split responses using the same Discord length-safe sending path as other bot text.
* On timeout, connection error, or empty response, send a short failure message instead of retrying indefinitely.
* If `[discord.interactive].mention_chat_enabled = false`, unknown mentions keep using the deterministic fallback/help response.

The provider abstraction targets the OpenAI-compatible `/v1/chat/completions` API, which covers Ollama and llama-server with a single implementation. A `null` provider satisfies the interface for `--no-llm` and tests.

## Discord Output

Scheduled mode uses webhooks.

**Length limits are a first-class requirement:** webhook `content` caps at 2000 characters; embed descriptions at 4096; total embed payload at 6000. The Discord renderer must measure and split: a briefing that exceeds limits is sent as multiple sequential messages, split on section boundaries first, then on item boundaries within a section. Never truncate silently.

**Pacing:** minimum 1 second between sequential webhook posts. On a `429`, honor `Retry-After` exactly; on repeated `429`s, back off exponentially (2s, 4s, 8s) up to 3 retries, then fail the send with a nonzero exit code.

Example output:

```
🌤 Weather
High 91°F, scattered storms likely after 2 PM.

📅 Calendar
9:00 AM — Standup
2:30 PM — Dentist

🗞 News
• Story title
  One-sentence summary in the persona's voice.
  Source: Example News — https://...

🤖 Tech
• Story title
  Why it matters, briefly.
  Source: Example Feed — https://...
```

## Interactive Discord Mode (Later Stage)

Slash commands first; deterministic mention routing second; persona chat third.

```
/briefing now
/briefing news
/briefing tech
/weather
/calendar today
/watch add term:<term>
/watch list
/search briefings query:<query>
/search items query:<query>
/feeds list
/summarize url:<url>
```

**Implementation note:** Discord interactions must be acknowledged within 3 seconds. Briefing generation takes longer, so every command defers (`defer()`) immediately and posts the result as a follow-up. This goes in the spec so it isn't discovered in production.

Slash commands call the same core functions as `briefing run` — no parallel code path.

Mention handling:

* Ignore messages from bots.
* Respond only when the bot is directly mentioned and the guild/channel/user allowlist permits the message.
* Strip bot mentions before routing.
* `help`, `what can you do`, and `commands` return deterministic command help, not an LLM answer.
* Known deterministic intents (`briefing`, `news`, `tech`, `weather`, `calendar`, `search`, `watch`) route to application code.
* Unknown mentions route to mention chat only when `[discord.interactive].mention_chat_enabled = true`; otherwise they return deterministic help.
* Mention chat is stateless in the first version. Conversation history, remembered facts, and retrieval from the briefing database are later-stage features.

## Stage Plan

### Stage 0: Skeleton
* Project structure, venv instructions, `config.example.toml`, CLI entrypoint, logging, config validation (pydantic, hard-fail on dangling references).
* **Acceptance:** `briefing run` prints a placeholder briefing to stdout (dry-run by default). An intentionally broken config produces a clear validation error.

### Stage 1: Discord Webhook Output
* Webhook sender with length-splitting and rate-limit handling. `--send` flag. `.env.example`. Built-in `ping` section.
* **Acceptance:** `briefing run --sections ping --send` posts a test message. `briefing run --sections ping` prints it without sending.

### Stage 2: RSS Engine
* Feed config, conditional fetching (ETag/Last-Modified), timestamp normalization, the selection algorithm as specified, dedup via `dedup_hash`, SQLite tracking, article-text sourcing rule, plain rendering.
* **Acceptance:** (a) `briefing run --sections news --no-llm` twice in a row — second run shows no duplicates; (b) `briefing run --sections news --no-llm --since 48h` then `--since 1h` — the second run shows no items older than 1 hour, proving window filtering works independently of dedup.

### Stage 3: Profiles and Flags
* Profiles from config, `--sections`, `--since`, `--max-items`, multiple RSS categories on the shared engine.
* **Acceptance:** `briefing run --profile tech` and `briefing run --sections news,tech --since 12h` both work.

### Stage 4: Weather and Calendar
* Weather via Open-Meteo (keyless; lat/lon from config). Calendar via `source = "json"` backend, with the `ics_url` and `caldav` backends stubbed behind the same dispatch. No LLM. Graceful one-line failure notice if a provider is unreachable or unconfigured.
* **Acceptance:** `briefing run --sections weather,calendar` produces deterministic output; with the JSON file missing, the briefing still completes with an error line for that section.

### Stage 5: LLM Summaries and Personas
* OpenAI-compatible provider, null provider, structural prompt/render split (LLM emits prose only), the pinned prompt/response contract with per-item fallback, persona loading with profile override and `--persona` flag, summary caching keyed by `(item, model, prompt_hash)`, fallback rendering.
* **Acceptance:** `briefing run --sections news` and `briefing run --sections news --no-llm` both work; killing the LLM server mid-run still produces a complete briefing; editing the persona file invalidates cached summaries.

### Stage 6: systemd Scheduling
* Example service and **timer** units; separate timers per profile for different days.

```ini
# briefing-daily.service
[Unit]
Description=Morning Briefing (daily profile)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/morning-briefing-bot
EnvironmentFile=/opt/morning-briefing-bot/.env
ExecStart=/opt/morning-briefing-bot/.venv/bin/briefing run --profile daily --send
```

```ini
# briefing-daily.timer
[Unit]
Description=Run morning briefing at 7:00

[Timer]
OnCalendar=Mon..Fri 07:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

`Persistent=true` so a briefing missed while the machine was off fires on next boot. Additional timers (e.g. `OnCalendar=Sat 09:00` with `--profile weekend`) reuse the same service pattern.
* **Acceptance:** timer fires and posts; `systemctl list-timers` shows next runs.

### Stage 7: Discord Slash Commands
* Long-running `discord.py` bot service. `/briefing now|news|tech`, `/weather`, `/calendar today`. Defer-then-followup on every command. Restricted to configured guild/channel/user IDs.
* **Acceptance:** `/briefing tech` in Discord generates and posts a tech briefing on demand.

### Stage 8: Mention Intent Routing and Help
* Mention-based interaction in allowed Discord contexts. Strip bot mentions, route obvious natural-language requests to the same core functions as slash commands, and keep `help` deterministic.
* Help output lists available slash commands and supported mention intents. Unknown mentions return help while mention chat is disabled.
* **Acceptance:** `@huginn help` returns command help; `@huginn weather` returns weather; `@huginn news` returns a news briefing; an unrelated mention returns help when chat is disabled.

### Stage 9: Stateless Persona Mention Chat
* Add a plain-text chat method to the OpenAI-compatible provider, with a chat-specific system prompt that loads the configured persona but does not use the briefing JSON prompt.
* Add `[discord.interactive].mention_chat_enabled`, `mention_chat_max_tokens`, and `mention_chat_temperature` config.
* Unknown allowed mentions call the local LLM and reply in the configured persona. Deterministic command routing and help still win before chat.
* Failure handling: timeout, connection error, disabled LLM, or empty response produces a short safe fallback; the bot service keeps running.
* **Acceptance:** with chat enabled and the local LLM running, `@huginn say something in your own voice` gets a persona-styled reply; `@huginn help` still returns command help; killing the LLM produces a controlled fallback.

### Stage 10: Memory and Search
* Search past briefings and seen items (the `briefing_items` history makes this cheap). Topic watch list: `/watch add`, `/watch list`, `/search briefings "Fedora"`.

### Stage 11: Conversational Memory (Optional)
* Add opt-in short conversation history per channel/user, bounded by token count and time.
* Add explicit remembered facts only through user-approved commands, not by silently storing arbitrary chat.
* Allow retrieval from past briefings/search results as explicit tool context when the user asks for it.
* **Acceptance:** chat can answer follow-up questions within a short session, but privacy-sensitive retention is off unless configured.

## Testing Requirements

pytest. Minimum:

* Config loads; dangling section/feed references fail validation.
* RSS entries normalize correctly (timestamps → UTC, dedup keys stable).
* Tracking-parameter variants of the same URL dedupe to one item; the same opaque GUID in two different feeds does NOT dedupe; the same permalink GUID in two feeds DOES.
* Selection algorithm respects priority, since, and max-items; `--since` overrides config `since_hours`.
* LLM response parsing: fenced JSON, missing item numbers, and garbage output all degrade per the contract without raising.
* `--no-llm` never constructs an LLM provider (assert via null provider / mock).
* Calendar JSON backend handles timed, all-day, and end-less events.
* Renderer output is non-empty and within Discord limits; over-length briefings split correctly.
* A failing feed does not fail the briefing.
* Persona file present/absent/overridden produces the expected system prompt; missing persona does not fail the run.
* Mention intent routing: help stays deterministic; known intents route to application code; unknown mentions route to help when chat is disabled.
* Mention chat prompt assembly uses the chat constraints plus persona, not the briefing JSON summary prompt.
* Mention chat failure paths return a controlled fallback and do not crash the Discord bot.

## Reliability Requirements

* Network errors: logged, skipped, never fatal to the briefing.
* One broken feed never breaks the section; one broken section never breaks the briefing.
* LLM failure falls back to plain rendering.
* Mention chat LLM failure falls back to a short deterministic message.
* Discord delivery failure returns a nonzero exit code (so systemd records the failure).
* Dry-run (the default) never sends.
* Database writes are idempotent; re-running after a crash is safe.

## Security Requirements

* `.env` is never committed; `.env.example` documents required variables.
* All secrets (webhook URL, ICS share link, CalDAV credentials, bot token) come from environment variables. A Proton Calendar share link is a capability URL and is treated as a secret.
* `calendar.json` isn't a secret in the credential sense, but it contains personal schedule data — keep it out of the repo (gitignored alongside `.env`).
* Webhook URLs and other secrets are never logged.
* All HTTP fetches (feeds, articles, weather, calendar) use timeouts.
* Interactive commands are restricted to configured server/channel/user IDs.
* Mention chat is restricted to the same configured server/channel/user IDs.
* Mention chat is stateless by default and does not persist user messages unless an explicit memory feature is enabled later.

## Definition of Done

The project is usable when:

```
briefing run --profile daily --send
```

posts a complete Discord briefing containing weather, calendar, and the configured RSS sections, in the configured persona's voice, while:

* avoiding duplicate feed items,
* surviving LLM, feed, and provider failures,
* respecting Discord length limits,
* using validated, config-driven sections and profiles,
* running from a Python virtual environment,
* and defaulting to dry-run for safe testing.
