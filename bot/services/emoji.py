"""Премиум-эмодзи бота. Владелец присылает их в админке, бот запоминает id и обычный эмодзи-замену.
Во всех сообщениях бота обычный эмодзи из набора заменяется премиум-версией (если у владельца бота
есть Telegram Premium, люди видят анимированный, иначе обычный)."""

import random
import re

from aiogram.types import Message

from bot import db

PACK: dict[str, list[str]] = {}       # обычный эмодзи → id премиум-версий
_SPLIT = re.compile(r"(<a\b[^>]*>.*?</a>|<tg-emoji\b[^>]*>.*?</tg-emoji>|<[^>]+>)", re.S)


async def load() -> None:
    PACK.clear()
    for row in await db.emoji_list():
        PACK.setdefault(row["alt"], []).append(row["emoji_id"])


def alts() -> list[str]:
    return list(PACK)


def decorate(html: str) -> str:
    """Меняет обычные эмодзи из набора на премиум. Внутри ссылок и тегов ничего не трогает."""
    if not PACK or not html:
        return html
    parts = _SPLIT.split(html)
    for i in range(0, len(parts), 2):   # чётные куски: обычный текст
        text = parts[i]
        for alt, ids in PACK.items():
            if alt in text:
                text = text.replace(alt, f'<tg-emoji emoji-id="{random.choice(ids)}">{alt}</tg-emoji>')
        parts[i] = text
    return "".join(parts)


def extract(message: Message) -> list[tuple[str, str]]:
    """Премиум-эмодзи из сообщения: [(id, обычный эмодзи)]. Смещения в Telegram считаются в UTF-16."""
    text = message.text or message.caption or ""
    raw = text.encode("utf-16-le")
    out = []
    for ent in (message.entities or message.caption_entities or []):
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            alt = raw[ent.offset * 2:(ent.offset + ent.length) * 2].decode("utf-16-le", "ignore")
            out.append((ent.custom_emoji_id, alt or "⭐"))
    return out
