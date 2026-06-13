# Morning Briefing Bot

Local-first Discord morning briefing bot. The current implementation provides
validated configuration, a CLI entrypoint, Discord webhook delivery, SQLite
state, and plain RSS briefings for configured news/tech sections.

## Setup

```bash
virtualenv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml
briefing run
```

Dry-run is the default. To send the ping section to Discord:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
briefing run --sections ping --send
```

RSS dry-runs:

```bash
briefing run --sections news --no-llm --since 24h
briefing run --sections tech --no-llm --max-items 5
briefing run --profile tech --no-llm
briefing run --sections news,tech --since 12h --no-llm
```

LLM summaries are optional. Configure any OpenAI-compatible local endpoint in
`[llm]`; if the endpoint is unavailable or returns malformed output, RSS
sections fall back to plain title/source/link rendering. Persona files control
voice only:

```bash
briefing run --sections news
briefing run --sections news --no-llm
briefing run --profile daily --persona personas/example-terse.md
```

Weather and calendar:

```bash
cp calendar.example.json calendar.json
briefing run --sections weather,calendar
```

`calendar.json` is ignored because it can contain personal schedule data.
The JSON backend supports timed events, all-day date-only events, optional
locations, and the configured lookahead window.

To use an ICS calendar URL, keep the URL in `.env`:

```bash
CALENDAR_ICS_URL="https://..."
```

Then set the local `config.toml` calendar section to:

```toml
[sections.calendar]
type = "calendar"
enabled = true
source = "ics_url"
ics_url_env = "CALENDAR_ICS_URL"
lookahead_hours = 24
```

The example general-news feeds are NPR and BBC News. The AP URL from the
original spec currently redirects to HTML rather than RSS, so it is not shipped
as an active example feed.

## Scheduling

Example systemd units live in `systemd/`. The templated service runs:

```text
briefing run --profile <profile> --send
```

Use separate timers for different profiles/days, for example
`briefing-daily.timer` for the `daily` profile and `briefing-tech.timer` for
the `tech` profile. See [systemd/README.md](systemd/README.md) for install and
check commands.

## Discord Slash Commands

Stage 7 adds a long-running Discord bot service:

```bash
briefing bot
```

Set `[discord.interactive].enabled = true` in local `config.toml`, set
`DISCORD_BOT_TOKEN` in `.env`, and keep `allowed_guild_ids` /
`allowed_channel_ids` restricted. The bot registers:

```text
/briefing now
/briefing news
/briefing tech
/weather
/calendar today
/watch add
/watch list
/search briefings
/search items
/feeds list
/summarize url
```

Mention-based chat is also available in allowed channels:

```text
@BotName weather
@BotName calendar today
@BotName news
@BotName tech briefing
@BotName morning briefing
```

For mention handling, enable the Message Content Intent for the bot in the
Discord developer portal.

## Memory And Search

Search saved local data:

```bash
briefing search briefings "Fedora"
briefing search items "Fedora"
```

Manage topic watch terms:

```bash
briefing watch add "Fedora Linux"
briefing watch list
```
