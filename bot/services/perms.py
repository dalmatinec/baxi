"""Кто считается админом: владельцы бота из OWNER_IDS, админы и создатель чата,
и анонимный админ (пишет от имени группы). Ответ Telegram кэшируем на 5 минут."""

import time

from aiogram import Bot
from aiogram.types import Message

from bot import config

_cache: dict[tuple[int, int], tuple[float, bool]] = {}
TTL = 300


async def is_admin(bot: Bot, message: Message) -> bool:
    chat_id = message.chat.id
    if message.sender_chat and message.sender_chat.id == chat_id:
        return True  # анонимный админ
    if not message.from_user:
        return False
    user_id = message.from_user.id
    if user_id in config.OWNER_IDS:
        return True
    key = (chat_id, user_id)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        ok = member.status in ("administrator", "creator")
    except Exception:
        ok = False
    _cache[key] = (time.time(), ok)
    return ok
