"""Перед любым обработчиком в группе: регистрируем чат, юзера и пишем сообщение в историю.
Так бот «видит» весь чат, даже когда молчит."""

import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot import db
from bot.textutil import full_name

log = logging.getLogger(__name__)

GROUPS = {"group", "supergroup"}
TRACKED = {"text", "sticker", "photo", "video", "animation", "voice", "video_note", "document", "audio"}


def describe(message: Message) -> str:
    """Сообщение в виде текста для истории: нейросеть не видит картинки, но знает, что они были."""
    caption = message.text or message.caption or ""
    ct = message.content_type
    if ct == "text":
        return caption
    emoji = message.sticker.emoji if message.sticker and message.sticker.emoji else ""
    marks = {"sticker": f"[стикер {emoji}]" if emoji else "[стикер]",
             "photo": "[фото]", "video": "[видео]", "animation": "[гифка]", "voice": "[голосовое]",
             "video_note": "[кружок]", "document": "[файл]", "audio": "[музыка]"}
    mark = marks.get(ct, "[сообщение]")
    return f"{mark} {caption}".strip()


class GroupTracker(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        if event.chat.type not in GROUPS:
            return await handler(event, data)
        try:
            chat = await db.ensure_chat(event.chat.id, event.chat.title or "")
            data["chat_row"] = chat
            user = event.from_user
            if user and not user.is_bot and not event.sender_chat and event.content_type in TRACKED:
                name = full_name(user.first_name, user.last_name)
                data["user_row"] = await db.touch_user(event.chat.id, user.id, name, user.username or "")
                reply_name = ""
                rt = event.reply_to_message
                if rt and rt.from_user:
                    bot = data["bot"]
                    reply_name = chat["bot_name"] if rt.from_user.id == bot.id else \
                        full_name(rt.from_user.first_name, rt.from_user.last_name)
                await db.add_history(event.chat.id, event.message_id, user.id, name, describe(event), reply_name)
        except Exception:
            log.exception("Не удалось записать сообщение в базу")
        return await handler(event, data)
