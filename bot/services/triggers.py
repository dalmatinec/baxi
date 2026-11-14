"""Триггеры: слово в чате → готовый ответ (текст, фото, видео, гифка, стикер), который задал админ чата."""

import re

from aiogram import Bot
from aiogram.types import Message

from bot import db
from bot.services.out import reply_params, say

_cache: dict[int, dict[str, object]] = {}
_CLEAN = re.compile(r"[^\wё\s]", re.I)


def norm(text: str) -> str:
    """«Правила!», «/правила», «правила?» → «правила»."""
    return " ".join(_CLEAN.sub(" ", (text or "").lower().replace("ё", "е")).split())


def forget(chat_id: int) -> None:
    _cache.pop(chat_id, None)


async def find(chat_id: int, text: str):
    if chat_id not in _cache:
        _cache[chat_id] = {norm(t["word"]): t for t in await db.list_triggers(chat_id)}
    words = _cache[chat_id]
    if not words or not text or len(text) > 60:
        return None
    return words.get(norm(text))


async def send(bot: Bot, chat_id: int, trig, reply_to: Message | None = None) -> None:
    kind, file_id, html = trig["media_kind"], trig["file_id"], trig["text_html"]
    rp = reply_params(reply_to)
    if kind == "photo":
        await bot.send_photo(chat_id, file_id, caption=html or None, parse_mode="HTML", reply_parameters=rp)
    elif kind == "video":
        await bot.send_video(chat_id, file_id, caption=html or None, parse_mode="HTML", reply_parameters=rp)
    elif kind == "gif":
        await bot.send_animation(chat_id, file_id, caption=html or None, parse_mode="HTML", reply_parameters=rp)
    elif kind == "sticker":
        await bot.send_sticker(chat_id, file_id, reply_parameters=rp)
    elif html:
        await say(bot, chat_id, html, reply_to=reply_to)


def extract(message: Message) -> tuple[str, str, str]:
    """(вид, file_id, текст HTML) из сообщения админа."""
    html = message.html_text if (message.text or message.caption) else ""
    if message.photo:
        return "photo", message.photo[-1].file_id, html
    if message.video:
        return "video", message.video.file_id, html
    if message.animation:
        return "gif", message.animation.file_id, html
    if message.sticker:
        return "sticker", message.sticker.file_id, ""
    return "", "", html
