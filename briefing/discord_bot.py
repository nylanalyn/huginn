from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord
from discord import app_commands

from briefing.config import AppConfig
from briefing.core import render_sections
from briefing.discord_webhook import split_sections_for_discord
from briefing.intent import route_mention_text
from briefing.sections.base import RunContext

LOG = logging.getLogger(__name__)


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
        routed = route_mention_text(mention_text)
        if routed.fallback:
            await message.reply(routed.fallback, mention_author=False)
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

        self.tree.add_command(briefing_group)

        @self.tree.command(name="weather", description="Show the weather")
        async def weather(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, sections=["weather"])

        calendar_group = app_commands.Group(name="calendar", description="Show calendar events")

        @calendar_group.command(name="today", description="Show today's calendar")
        async def calendar_today(interaction: discord.Interaction) -> None:
            await self._handle_briefing(interaction, sections=["calendar"])

        self.tree.add_command(calendar_group)

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

        rendered = await asyncio.to_thread(self._render_for_interaction, profile, sections)
        messages = split_sections_for_discord(rendered)
        if not messages:
            messages = ["(empty briefing)"]
        for message in messages:
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
        return render_sections(section_names, context)


def _identity_from_interaction(interaction: discord.Interaction) -> InteractionIdentity:
    return InteractionIdentity(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        user_id=interaction.user.id,
    )


def _strip_bot_mentions(content: str, display_name: str) -> str:
    return content.replace("@" + display_name, "").strip()


async def run_discord_bot(config: AppConfig, token: str) -> None:
    bot = BriefingDiscordBot(config)
    async with bot:
        await bot.start(token)
