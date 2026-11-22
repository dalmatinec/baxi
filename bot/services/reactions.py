"""Реакции бота на сообщения: 👍, ❤, 😁. Как у живого человека, редко и по делу, без нейросети.

Когда ставит:
  - на «спасибо» или смех ответом на его сообщение: реакция вместо текстового ответа (если сообщение короткое);
  - иногда на обычные сообщения, когда сам не отвечает (около 4%);
  - когда хотел ответить, но ответ вышел бы повтором.
Ограничения: не больше 4 реакций в час на чат, одному человеку не две подряд. Выключается в Фишках («Реакции»).
Какую ставит: смех → 😁, спасибо, любовь, комплимент → ❤, остальное → 👍."""

import logging
import random
import re
import time

from aiogram import Bot
from aiogram.types import Message, ReactionTypeEmoji

from bot.textutil import is_laugh

log = logging.getLogger(__name__)

LIKE, LOVE, LAUGH = "👍", "❤", "😁"
PER_HOUR = 4
CHANCE = 0.04

_LOVE = re.compile(r"спасиб|спс|пасиб|благодар|люблю|обожаю|красав|умниц|молодец|лучший|лучшая|рахмет|❤|😍|🥰|💕|сяб",
                   re.I)
_times: dict[int, list[float]] = {}
_last_user: dict[int, int] = {}


def choose(text: str) -> str:
    if is_laugh(text) or re.search(r"а?х(а|е){2,}|ору|ржу|😂|🤣", (text or "").lower()):
        return LAUGH
    if _LOVE.search(text or ""):
        return LOVE
    return LIKE


def allowed(chat_id: int, user_id: int, now: float | None = None) -> bool:
    now = now or time.time()
    recent = [t for t in _times.get(chat_id, []) if now - t < 3600]
    _times[chat_id] = recent
    return len(recent) < PER_HOUR and _last_user.get(chat_id) != user_id


def short_thanks_or_laugh(text: str) -> bool:
    """Короткое «спасибо», «ахах», «красава»: на такое человек ставит реакцию, а не пишет ответ."""
    t = (text or "").strip()
    return 0 < len(t.split()) <= 4 and choose(t) in (LOVE, LAUGH)


async def react(bot: Bot, chat, message: Message, emoji: str | None = None) -> bool:
    """Поставить реакцию, если в чате разрешено и лимит не выбран. True, если поставил."""
    if not chat["reactions"] or not message.from_user:
        return False
    chat_id, user_id = message.chat.id, message.from_user.id
    if not allowed(chat_id, user_id):
        return False
    emoji = emoji or choose(message.text or message.caption or "")
    try:
        await bot.set_message_reaction(chat_id, message.message_id, [ReactionTypeEmoji(emoji=emoji)])
    except Exception as exc:   # в чате реакции ограничены или сообщение удалили
        log.debug("Реакция %s в чате %s не встала: %s", emoji, chat_id, exc)
        return False
    _times.setdefault(chat_id, []).append(time.time())
    _last_user[chat_id] = user_id
    return True


async def maybe(bot: Bot, chat, message: Message, chance: float = CHANCE) -> bool:
    return random.random() < chance and await react(bot, chat, message)
