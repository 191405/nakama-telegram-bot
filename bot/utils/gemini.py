"""Google Gemini AI client for Nakama Anime Concierge and Natural Assistant."""

from __future__ import annotations

import html
import logging
import re
from typing import Any
import aiohttp

from bot.config import settings
from bot.utils.memory import add_to_conversation, get_conversation_history

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
]

SYSTEM_PROMPT = """You are Nakama, a friendly, intelligent, and authentic conversational companion.

Your personality and speech guidelines:
- Talk like a real person in a natural, warm, and engaging conversational manner.
- Do NOT sound like a robotic Telegram bot or corporate customer service.
- ABSOLUTELY NEVER mention, recommend, or use bot forward-slash commands (do NOT say '/search', '/feed', '/browse', '/request', '/ask', '/profile', '/start', etc.). Talk like an actual human friend chatting on Telegram.
- Understand natural language effortlessly, including casual chat, slang, typos, and out-of-context questions.
- Answer ANY question the user asks with deep knowledge, clarity, and warmth—even general questions completely outside of anime (science, history, coding, philosophy, gaming, cooking, pop culture, life advice, or casual everyday banter). You are well-rounded and versatile.
- When asked about anime, manga, or pop culture, you are enthusiastic and knowledgeable, giving tailored recommendations and explaining lore or watch orders without major plot spoilers.
- Keep responses concise, helpful, and pleasant to read on a mobile screen (under 300 words).
- Use clean Telegram HTML formatting (<b>bold</b>, <i>italic</i>) where helpful for readability. Do NOT use markdown asterisks (*text* or **text**).
"""


def format_for_telegram(text: str) -> str:
    """Ensure text is formatted cleanly for Telegram HTML without markdown artifacts or slash commands."""
    t = text.strip()
    # Convert markdown headers
    t = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", t, flags=re.MULTILINE)
    # Convert **bold** to <b>bold</b>
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    # Convert *italic* or _italic_ to <i>italic</i>
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<i>\1</i>", t)
    # Remove accidental bot forward-slash command suggestions
    t = re.sub(
        r"(?:type\s+|use\s+|send\s+)?/(?:search|feed|browse|request|ask|profile|start|help|themes|whatanime)\b",
        "search by title",
        t,
        flags=re.IGNORECASE,
    )
    return t


async def ask_gemini_anime_concierge(
    query: str = "",
    user_id: int | None = None,
    system_grounding: str | None = None,
    audio_base64: str | None = None,
    audio_mime_type: str = "audio/ogg",
    api_key: str | None = None,
) -> str:
    """Ask Google Gemini with conversation memory, voice notes, and live system grounding."""
    key = api_key or settings.gemini_api_key
    if not key:
        return (
            "Hey! I'd love to chat and answer all your questions, but my conversational brain "
            "hasn't been connected with an API key yet.\n\n"
            "An admin can activate my AI anytime by getting a free key from Google AI Studio "
            "(aistudio.google.com) and sending:\n"
            "<code>/setgemini YOUR_KEY</code>\n\n"
            "Once connected, we can talk about anything you'd like!"
        )

    # Build multi-turn contents from user session
    contents: list[dict[str, Any]] = []
    if user_id:
        contents.extend(get_conversation_history(user_id))

    # Append current user prompt parts (text and/or audio)
    user_parts: list[dict[str, Any]] = []
    if audio_base64:
        user_parts.append({
            "inlineData": {
                "mimeType": audio_mime_type,
                "data": audio_base64,
            }
        })
    if query:
        user_parts.append({"text": query})
    elif audio_base64:
        user_parts.append({
            "text": "Listen to this voice message, transcribe the user's intent, and respond warmly in your persona."
        })

    contents.append({
        "role": "user",
        "parts": user_parts,
    })

    # Combine personality with live system grounding
    instruction_text = SYSTEM_PROMPT
    if system_grounding:
        instruction_text = f"{SYSTEM_PROMPT}\n\n{system_grounding}"

    payload: dict[str, Any] = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": instruction_text}]
        },
        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 700,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            for model in SUPPORTED_MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                try:
                    async with session.post(
                        url, json=payload, timeout=aiohttp.ClientTimeout(total=20)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            candidates = data.get("candidates", [])
                            if not candidates:
                                continue
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if not parts:
                                continue
                            text = parts[0].get("text", "")
                            if text:
                                # Save turns to memory
                                if user_id:
                                    memory_text = query if query else "[Voice Message]"
                                    add_to_conversation(user_id, "user", memory_text)
                                    add_to_conversation(user_id, "model", text)
                                return format_for_telegram(text)
                        else:
                            err_text = await resp.text()
                            logger.warning(
                                "Gemini model %s returned %s: %s",
                                model,
                                resp.status,
                                err_text[:150],
                            )
                except Exception as model_err:
                    logger.warning("Gemini model %s failed: %s", model, model_err)
                    continue

            return (
                "I'm momentarily catching my breath! "
                "Please try asking again in a few moments."
            )
    except Exception as exc:
        logger.error("Error calling Gemini API: %s", exc)
        return "Something went wrong while connecting to my thoughts. Please try again in a moment!"
