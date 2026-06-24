from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord
from discord import app_commands

from briefing.actions import feeds_list_text, summarize_url_text
from briefing.config import AppConfig
from briefing.core import render_sections
from briefing.discord_webhook import split_sections_for_discord, split_text_for_discord
from briefing.intent import HELP_MESSAGE, RoutedIntent, route_mention_text
from briefing.llm.base import LlmProvider
from briefing.llm.openai_compat import OpenAICompatProvider
from briefing.llm.prompt import build_chat_system_prompt
from briefing.render.text import render_briefing
from briefing.memory import (
    add_watch_text,
    clear_remembered_facts_text,
    conversation_context_text,
    list_remembered_facts_text,
    list_watch_text,
    remember_fact_text,
    retrieval_context_text,
    search_briefings_text,
    search_items_text,
)
from briefing.sections.base import RunContext
from briefing.db import Database

LOG = logging.getLogger(__name__)
CHAT_UNAVAILABLE_MESSAGE = "Mention chat is unavailable right now."


@dataclass(frozen=True)
class InteractionIdentity:
    guild_id: int | None
    channel_id: int | None
    user_id: int


def interaction_allowed(config: AppConfig, identity: InteractionIdentity) -> bool:
    interactive = config.discord.interactive
    if interactive.allowed_guild_ids and identity.guild_id not in interactive.allowed_guild_ids:
        return False
    if interactive.allowed_channel_ids and identity.channel_id not in interactive.allowed_channel_ids:
        return False
    if interactive.allowed_user_ids and identity.user_id not in interactive.allowed_user_ids:
        return False
    return True


class BriefingDiscordBot(discord.Client):
    def __init__(self, config: AppConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self._synced = False
        self._register_commands()

    async def setup_hook(self) -> None:
        for guild_id in self.config.discord.interactive.allowed_guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        if not self.config.discord.interactive.allowed_guild_ids:
            await self.tree.sync()
        self._synced = True

    async def on_ready(self) -> None:
        LOG.info("Discord bot connected as %s; commands synced=%s", self.user, self._synced)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        if self.user not in message.mentions:
            return
        identity = InteractionIdentity(
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            user_id=message.author.id,
        )
        if not interaction_allowed(self.config, identity):
            await message.reply("This bot is not enabled for this Discord context.", mention_author=False)
            return

        mention_text = _strip_bot_mentions(message.clean_content, self.user.display_name)
        routed = route_mention_text(
            mention_text,
            profile_names=set(self.config.profiles),
            section_names=set(self.config.sections),
        )
        if routed.fallback:
            if (
                routed.fallback_reason == "unknown"
                and self.config.discord.interactive.mention_chat_enabled
            ):
                async with message.channel.typing():
                    text = await asyncio.to_thread(
                        self._chat_for_interaction,
                        mention_text,
                        identity,
                    )
                chunks = split_text_for_discord(text)
                if chunks:
                    await message.reply(chunks[0], mention_author=False)
                    for content in chunks[1:]:
                        await message.channel.send(content)
                return
            await message.reply(routed.fallback, mention_author=False)
            return

        if routed.text_action:
            async with message.channel.typing():
                text = await asyncio.to_thread(self._text_for_interaction, routed, identity)
            for content in _command_reply_chunks(text):
                await message.channel.send(content)
            return

        async with message.channel.typing():
            rendered = await asyncio.to_thread(
                self._render_for_interaction,
                routed.profile,
                routed.sections,
            )
        messages = split_sections_for_discord(rendered)
        if not messages:
            messages = ["(empty briefing)"]
        for content in messages:
            await message.channel.send(content)

    def _register_commands(self) -> None:
        briefing_group = app_commands.Group(name="briefing", description="Generate a briefing")

        @briefing_group.command(name="now", description="Generate the daily briefing")
        async def briefing_now(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, profile="daily")

        @briefing_group.command(name="news", description="Generate a news briefing")
        async def briefing_news(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, sections=["news"])

        @briefing_group.command(name="tech", description="Generate a tech briefing")
        async def briefing_tech(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, sections=["tech"])

        @briefing_group.command(name="profile", description="Generate a named briefing profile")
        async def briefing_profile(interaction: discord.Interaction, profile: str) -> None:
            await self._handle_briefing(interaction, profile=profile)

        @briefing_profile.autocomplete("profile")
        async def briefing_profile_autocomplete(
            interaction: discord.Interaction,
            current: str,
        ) -> list[app_commands.Choice[str]]:
            del interaction
            needle = current.casefold()
            return [
                app_commands.Choice(name=name, value=name)
                for name in sorted(self.config.profiles)
                if not needle or needle in name.casefold()
            ][:25]

        self.tree.add_command(briefing_group)

        @self.tree.command(name="help", description="Show Huginn commands")
        async def help_command(interaction: discord.Interaction) -> None:
            await self._handle_text_command(interaction, lambda: HELP_MESSAGE)

        @self.tree.command(name="weather", description="Show the weather")
        async def weather(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, sections=["weather"])

        calendar_group = app_commands.Group(name="calendar", description="Show calendar events")

        @calendar_group.command(name="today", description="Show today's calendar")
        async def calendar_today(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, sections=["calendar"])

        self.tree.add_command(calendar_group)

        watch_group = app_commands.Group(name="watch", description="Manage topic watch terms")

        @watch_group.command(name="add", description="Add a topic watch term")
        async def watch_add(interaction: discord.Interaction, term: str) -> None:
            await self._handle_text_command(
                interaction,
                lambda: add_watch_text(Database(self.config.bot.database_path), term),
            )

        @watch_group.command(name="list", description="List topic watch terms")
        async def watch_list(interaction: discord.Interaction) -> None:
            await self._handle_text_command(
                interaction,
                lambda: list_watch_text(Database(self.config.bot.database_path)),
            )

        self.tree.add_command(watch_group)

        search_group = app_commands.Group(name="search", description="Search saved briefing data")

        @search_group.command(name="briefings", description="Search past briefings")
        async def search_briefings(interaction: discord.Interaction, query: str) -> None:
            await self._handle_text_command(
                interaction,
                lambda: search_briefings_text(Database(self.config.bot.database_path), query, limit=5),
            )

        @search_group.command(name="items", description="Search seen RSS items")
        async def search_items(interaction: discord.Interaction, query: str) -> None:
            await self._handle_text_command(
                interaction,
                lambda: search_items_text(Database(self.config.bot.database_path), query, limit=5),
            )

        self.tree.add_command(search_group)

        feeds_group = app_commands.Group(name="feeds", description="Inspect configured feeds")

        @feeds_group.command(name="list", description="List configured feeds")
        async def feeds_list(interaction: discord.Interaction) -> None:
            await self._handle_text_command(interaction, lambda: feeds_list_text(self.config))

        self.tree.add_command(feeds_group)

        summarize_group = app_commands.Group(name="summarize", description="Summarize fetched content")

        @summarize_group.command(name="url", description="Summarize a URL")
        async def summarize_url(interaction: discord.Interaction, url: str) -> None:
            await self._handle_text_command(interaction, lambda: summarize_url_text(self.config, url))

        self.tree.add_command(summarize_group)

        memory_group = app_commands.Group(name="memory", description="Manage opt-in remembered facts")

        @memory_group.command(name="remember", description="Remember an explicit fact")
        async def memory_remember(interaction: discord.Interaction, fact: str) -> None:
            await self._handle_text_command(
                interaction,
                lambda: remember_fact_text(
                    self.config,
                    Database(self.config.bot.database_path),
                    user_id=interaction.user.id,
                    fact=fact,
                ),
            )

        @memory_group.command(name="list", description="List remembered facts")
        async def memory_list(interaction: discord.Interaction) -> None:
            await self._handle_text_command(
                interaction,
                lambda: list_remembered_facts_text(
                    self.config,
                    Database(self.config.bot.database_path),
                    user_id=interaction.user.id,
                ),
            )

        @memory_group.command(name="clear", description="Clear remembered facts")
        async def memory_clear(interaction: discord.Interaction) -> None:
            await self._handle_text_command(
                interaction,
                lambda: clear_remembered_facts_text(
                    self.config,
                    Database(self.config.bot.database_path),
                    user_id=interaction.user.id,
                ),
            )

        self.tree.add_command(memory_group)

    async def _handle_briefing(
        self,
        interaction: discord.Interaction,
        *,
        profile: str | None = None,
        sections: list[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        if not interaction_allowed(self.config, _identity_from_interaction(interaction)):
            await interaction.followup.send("This bot is not enabled for this Discord context.")
            return
        if profile and profile not in self.config.profiles:
            available = ", ".join(sorted(self.config.profiles)) or "(none)"
            await interaction.followup.send(
                f"Unknown briefing profile '{profile}'. Available profiles: {available}"
            )
            return

        rendered = await asyncio.to_thread(self._render_for_interaction, profile, sections)
        messages = split_sections_for_discord(rendered)
        if not messages:
            messages = ["(empty briefing)"]
        for message in messages:
            await interaction.followup.send(message)

    async def _handle_text_command(self, interaction: discord.Interaction, callback) -> None:
        await interaction.response.defer(thinking=True)
        if not interaction_allowed(self.config, _identity_from_interaction(interaction)):
            await interaction.followup.send("This bot is not enabled for this Discord context.")
            return
        try:
            text = await asyncio.to_thread(callback)
        except Exception as exc:
            LOG.warning("Discord text command failed: %s", exc)
            await interaction.followup.send(f"Command failed: {exc}")
            return
        for message in _command_reply_chunks(text):
            await interaction.followup.send(message)

    def _render_for_interaction(
        self,
        profile: str | None,
        sections: list[str] | None,
    ):
        section_names = sections
        if profile:
            section_names = self.config.profiles[profile].sections
        if not section_names:
            section_names = ["ping"]
        context = RunContext(config=self.config, profile_name=profile, format_name="discord")
        rendered = render_sections(section_names, context)
        self._record_briefing(profile, section_names, rendered)
        return rendered

    def _record_briefing(
        self,
        profile: str | None,
        section_names: list[str],
        rendered,
    ) -> None:
        # Persist the briefing so item dedup, history, and `/search briefings`
        # work for the interactive bot the same way they do for webhook sends.
        try:
            Database(self.config.bot.database_path).record_sent_briefing(
                profile=profile,
                section_names=section_names,
                rendered_sections=rendered,
                body=render_briefing(rendered),
            )
        except Exception as exc:
            LOG.warning("Failed to record interactive briefing: %s", exc)

    def _text_for_interaction(self, routed: RoutedIntent, identity: InteractionIdentity) -> str:
        database = Database(self.config.bot.database_path)
        try:
            if routed.text_action == "watch_add":
                return add_watch_text(database, routed.text_argument or "")
            if routed.text_action == "watch_list":
                return list_watch_text(database)
            if routed.text_action == "search_briefings":
                return search_briefings_text(database, routed.text_argument or "", limit=5)
            if routed.text_action == "search_items":
                return search_items_text(database, routed.text_argument or "", limit=5)
            if routed.text_action == "memory_remember":
                return remember_fact_text(
                    self.config,
                    database,
                    user_id=identity.user_id,
                    fact=routed.text_argument or "",
                )
            if routed.text_action == "memory_list":
                return list_remembered_facts_text(self.config, database, user_id=identity.user_id)
            if routed.text_action == "memory_clear":
                return clear_remembered_facts_text(self.config, database, user_id=identity.user_id)
        except Exception as exc:
            LOG.warning("Discord mention text command failed: %s", exc)
            return f"Command failed: {exc}"
        return "Command failed: unknown mention action."

    def _chat_for_interaction(self, text: str, identity: InteractionIdentity | None = None) -> str:
        if not self.config.llm.enabled:
            return CHAT_UNAVAILABLE_MESSAGE
        database = Database(self.config.bot.database_path)
        try:
            context = RunContext(config=self.config, format_name="discord")
            memory_context = ""
            if identity:
                memory_context = "\n\n".join(
                    part
                    for part in [
                        conversation_context_text(
                            self.config,
                            database,
                            guild_id=identity.guild_id,
                            channel_id=identity.channel_id or 0,
                            user_id=identity.user_id,
                        ),
                        retrieval_context_text(self.config, database, text),
                    ]
                    if part
                )
            provider = self._build_llm_provider()
            response = provider.chat(
                system_prompt=build_chat_system_prompt(context, memory_context=memory_context),
                message=text,
                max_tokens=self.config.discord.interactive.mention_chat_max_tokens,
                temperature=self.config.discord.interactive.mention_chat_temperature,
            ).strip()
        except Exception as exc:
            LOG.warning("Discord mention chat failed: %s", exc)
            return CHAT_UNAVAILABLE_MESSAGE
        if not response:
            return CHAT_UNAVAILABLE_MESSAGE
        if identity and self.config.discord.interactive.conversation_memory_enabled:
            database.add_conversation_message(
                guild_id=identity.guild_id,
                channel_id=identity.channel_id or 0,
                user_id=identity.user_id,
                role="user",
                content=text,
            )
            database.add_conversation_message(
                guild_id=identity.guild_id,
                channel_id=identity.channel_id or 0,
                user_id=identity.user_id,
                role="assistant",
                content=response,
            )
        return response

    def _build_llm_provider(self) -> LlmProvider:
        return OpenAICompatProvider(self.config.llm)


def _identity_from_interaction(interaction: discord.Interaction) -> InteractionIdentity:
    return InteractionIdentity(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        user_id=interaction.user.id,
    )


def _strip_bot_mentions(content: str, display_name: str) -> str:
    return content.replace("@" + display_name, "").strip()


def _command_reply_chunks(text: str) -> list[str]:
    # Command/text-action replies already contain their own content, so they
    # are sent as plain chunks (no section header). Empty results are explicit.
    return split_text_for_discord(text) or ["(empty result)"]


async def run_discord_bot(config: AppConfig, token: str) -> None:
    bot = BriefingDiscordBot(config)
    async with bot:
        await bot.start(token)
