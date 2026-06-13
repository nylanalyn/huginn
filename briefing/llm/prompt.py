from __future__ import annotations

import logging
from pathlib import Path

from briefing.config import AppConfig
from briefing.sections.base import RunContext
from briefing.utils.hashing import sha256_text

LOG = logging.getLogger(__name__)

FACTUAL_INSTRUCTIONS = """You summarize only the news items provided by the application.
Do not invent stories, URLs, sources, quotes, dates, or facts.
Return prose for the numbered items only. The application will attach titles,
sources, and links deterministically, so do not include links or source names.
If an item has too little context, write a cautious, brief summary from the
given title and text only."""

OUTPUT_INSTRUCTIONS = """Respond with only a JSON object matching this shape:
{"lede": "optional short section opener or empty string", "summaries": [{"item_num": 1, "summary": "..."}]}"""

CHAT_INSTRUCTIONS = """You are Huginn, a private Discord bot for the user.
Respond naturally in the configured persona.
Be concise unless the user asks for depth.
Do not claim to have checked live data, Discord history, files, feeds, weather, calendar, or the internet unless that context was explicitly provided in the prompt.
If the user asks for a briefing, news, tech, weather, calendar, search, watch-list management, or help, those are application commands and should be handled by deterministic routing before chat.
Do not invent personal memories. If memory context is provided, use only that context for remembered facts or recent conversation. If no memory context is provided, say you do not have memory of it."""

NEUTRAL_PERSONA = "Use a neutral, concise briefing voice. Keep each summary to one or two sentences."


def resolve_persona_path(context: RunContext) -> str:
    if context.persona_path:
        return context.persona_path
    if context.profile_name:
        profile = context.config.profiles.get(context.profile_name)
        if profile and profile.persona_path:
            return profile.persona_path
    return context.config.llm.persona_path


def load_persona(context: RunContext) -> str:
    persona_path = resolve_persona_path(context)
    try:
        return Path(persona_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        LOG.warning("Persona file %s could not be read: %s", persona_path, exc)
        return NEUTRAL_PERSONA


def build_system_prompt(context: RunContext) -> str:
    persona = load_persona(context)
    return "\n\n".join(
        [
            FACTUAL_INSTRUCTIONS,
            OUTPUT_INSTRUCTIONS,
            "Persona voice follows. Factual instructions above override persona text on any conflict.",
            persona,
        ]
    )


def build_chat_system_prompt(context: RunContext, memory_context: str | None = None) -> str:
    persona = load_persona(context)
    parts = [
        CHAT_INSTRUCTIONS,
        "Persona voice follows. Chat behavior constraints above override persona text on any conflict.",
        persona,
    ]
    if memory_context:
        parts.extend(
            [
                "Explicit local context follows. Treat it as partial and local-only; do not infer beyond it.",
                memory_context,
            ]
        )
    return "\n\n".join(parts)


def prompt_hash(system_prompt: str) -> str:
    return sha256_text(system_prompt)


def llm_enabled_for_section(context: RunContext, section_use_llm: bool) -> bool:
    return bool(context.config.llm.enabled and section_use_llm and not context.no_llm)
