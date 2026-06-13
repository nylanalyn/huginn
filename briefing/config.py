from __future__ import annotations

import logging
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

LOG = logging.getLogger(__name__)


BUILT_IN_SECTIONS = {"ping"}


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded or validated."""


class WarnUnknownModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    def warn_unknown_keys(self, path: str) -> None:
        extras = getattr(self, "__pydantic_extra__", None) or {}
        for key in extras:
            LOG.warning("Unknown config key: %s.%s", path, key)


class SectionType(StrEnum):
    WEATHER = "weather"
    CALENDAR = "calendar"
    RSS = "rss"


class BotConfig(WarnUnknownModel):
    timezone: str = "America/New_York"
    database_path: str = "briefing.sqlite3"


class DiscordInteractiveConfig(WarnUnknownModel):
    enabled: bool = False
    token_env: str = "DISCORD_BOT_TOKEN"
    allowed_guild_ids: list[int] = Field(default_factory=list)
    allowed_channel_ids: list[int] = Field(default_factory=list)
    allowed_user_ids: list[int] = Field(default_factory=list)
    mention_chat_enabled: bool = False
    mention_chat_max_tokens: int = 500
    mention_chat_temperature: float = 0.7
    conversation_memory_enabled: bool = False
    conversation_memory_max_messages: int = 8
    conversation_memory_max_tokens: int = 1000
    conversation_memory_max_age_minutes: int = 60
    remembered_facts_enabled: bool = False
    remembered_facts_max_items: int = 20
    retrieval_context_enabled: bool = False
    retrieval_context_limit: int = 3


class DiscordConfig(WarnUnknownModel):
    webhook_url_env: str = "DISCORD_WEBHOOK_URL"
    interactive: DiscordInteractiveConfig = Field(default_factory=DiscordInteractiveConfig)


class LlmConfig(WarnUnknownModel):
    enabled: bool = True
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3.1:8b"
    temperature: float = 0.2
    timeout_seconds: int = 600
    max_tokens: int = 700
    persona_path: str = "personas/default.md"


class ProfileConfig(WarnUnknownModel):
    sections: list[str]
    persona_path: str | None = None

    @field_validator("sections")
    @classmethod
    def sections_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("profile sections must not be empty")
        return value


class WeatherSectionConfig(WarnUnknownModel):
    type: Literal[SectionType.WEATHER]
    enabled: bool = True
    provider: str = "open-meteo"
    latitude: float
    longitude: float
    units: Literal["imperial", "metric"] = "imperial"


class CalendarSectionConfig(WarnUnknownModel):
    type: Literal[SectionType.CALENDAR]
    enabled: bool = True
    source: Literal["json", "ics_url", "caldav"] = "json"
    json_path: str | None = None
    ics_url_env: str | None = None
    caldav_url_env: str | None = None
    caldav_user_env: str | None = None
    caldav_pass_env: str | None = None
    lookahead_hours: int = 24


class RssSectionConfig(WarnUnknownModel):
    type: Literal[SectionType.RSS]
    enabled: bool = True
    use_llm: bool = True
    max_items: int = 8
    max_items_per_feed: int | None = None
    since_hours: int = 24
    extract_full_article: bool = False
    feeds: list[str]

    @field_validator("feeds")
    @classmethod
    def feeds_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("rss section feeds must not be empty")
        return value


SectionConfig = WeatherSectionConfig | CalendarSectionConfig | RssSectionConfig


class FeedConfig(WarnUnknownModel):
    name: str
    url: str
    type: Literal["rss", "html_links", "noaa_alerts"] = "rss"
    base_url: str | None = None
    link_pattern: str | None = None
    priority: int = 0
    filter_include_keywords: list[str] = Field(default_factory=list)
    filter_exclude_keywords: list[str] = Field(default_factory=list)
    filter_area_keywords: list[str] = Field(default_factory=list)


class AppConfig(WarnUnknownModel):
    bot: BotConfig = Field(default_factory=BotConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    sections: dict[str, SectionConfig] = Field(default_factory=dict)
    feeds: dict[str, FeedConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "AppConfig":
        errors: list[str] = []
        defined_sections = set(self.sections) | BUILT_IN_SECTIONS

        for profile_name, profile in self.profiles.items():
            for section_name in profile.sections:
                if section_name not in defined_sections:
                    errors.append(
                        f"profile '{profile_name}' references undefined section '{section_name}'"
                    )

        for section_name, section in self.sections.items():
            if isinstance(section, RssSectionConfig):
                for feed_key in section.feeds:
                    if feed_key not in self.feeds:
                        errors.append(
                            f"section '{section_name}' references undefined feed '{feed_key}'"
                        )

        if errors:
            raise ValueError("; ".join(errors))
        return self

    def warn_unknown_keys(self, path: str = "config") -> None:
        super().warn_unknown_keys(path)
        self.bot.warn_unknown_keys("bot")
        self.discord.warn_unknown_keys("discord")
        self.discord.interactive.warn_unknown_keys("discord.interactive")
        self.llm.warn_unknown_keys("llm")
        for name, profile in self.profiles.items():
            profile.warn_unknown_keys(f"profiles.{name}")
        for name, section in self.sections.items():
            section.warn_unknown_keys(f"sections.{name}")
        for name, feed in self.feeds.items():
            feed.warn_unknown_keys(f"feeds.{name}")


def load_config(path: str | Path = "config.toml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        example_path = Path("config.example.toml")
        if example_path.exists():
            LOG.warning("Config %s not found; using %s", config_path, example_path)
            config_path = example_path
        else:
            raise ConfigError(f"Config file not found: {path}")

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    try:
        config = AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(config_path, exc)) from exc
    except ValueError as exc:
        raise ConfigError(f"Invalid config in {config_path}: {exc}") from exc

    config.warn_unknown_keys()
    return config


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return f"Invalid config in {path}: " + "; ".join(parts)


def parse_section_names(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        raise ConfigError("--sections must include at least one section")
    return names


def select_sections(
    config: AppConfig,
    profile_name: str | None,
    section_names: list[str] | None,
) -> list[str]:
    if profile_name and section_names:
        raise ConfigError("Use either --profile or --sections, not both")
    if profile_name:
        try:
            return config.profiles[profile_name].sections
        except KeyError as exc:
            raise ConfigError(f"Unknown profile '{profile_name}'") from exc
    if section_names:
        defined_sections = set(config.sections) | BUILT_IN_SECTIONS
        missing = [name for name in section_names if name not in defined_sections]
        if missing:
            raise ConfigError(f"Unknown section(s): {', '.join(missing)}")
        return section_names
    return ["ping"]


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
