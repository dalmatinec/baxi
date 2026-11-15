"""Перед любым обработчиком в группе: регистрируем чат, юзера и пишем сообщение в историю.
Так бот «видит» весь чат, даже когда молчит."""

import logging

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot import ai, db
from bot.textutil import full_name, is_laugh, is_mat

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


LAUGH_EMOJI = {"😂", "🤣", "😹", "😆"}


def real_reply(message: Message) -> Message | None:
    """Сообщение, на которое ответили. В форумах «ответ» на начало темы ответом не считаем."""
    rt = message.reply_to_message
    if rt is None or rt.forum_topic_created:
        return None
    if message.is_topic_message and rt.message_id == message.message_thread_id:
        return None
    return rt


class GroupTracker(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        if event.chat.type == "private" and event.from_user and not event.from_user.is_bot:
            try:  # запоминаем, кто писал в личку: для рассылок и охвата рекламы
                await db.touch_dm(event.from_user.id, full_name(event.from_user.first_name, event.from_user.last_name),
                                  event.from_user.username or "")
            except Exception:
                log.exception("Не записал пользователя лички")
        if event.chat.type not in GROUPS:
            return await handler(event, data)
        try:
            if event.migrate_from_chat_id:  # группа стала супергруппой: переносим настройки
                await db.migrate_chat(event.migrate_from_chat_id, event.chat.id)
            chat = await db.ensure_chat(event.chat.id, event.chat.title or "")
            if not chat["approved"]:
                # чат не одобрен: бот молчит, а владельцу уходит заявка (один раз)
                from bot.services import approval
                await approval.request(data["bot"], event.chat.id, event.chat.title or "")
                return None
            from bot.services import license
            if license.sleeping():
                return None  # копия white label не оплачена: в чатах молчим
            data["chat_row"] = chat
            ai.CURRENT_CHAT.set(chat)  # для тарифа: бесплатным чатам нейросеть не отвечает
            user = event.from_user
            if user and not user.is_bot and not event.sender_chat and event.content_type in TRACKED:
                name = full_name(user.first_name, user.last_name, user.username)
                data["user_row"] = await db.touch_user(event.chat.id, user.id, name, user.username or "")
                reply_name, reply_user_id = "", 0
                rt = real_reply(event)
                if rt and rt.from_user:
                    bot = data["bot"]
                    reply_user_id = rt.from_user.id
                    reply_name = chat["bot_name"] if rt.from_user.id == bot.id else \
                        full_name(rt.from_user.first_name, rt.from_user.last_name, rt.from_user.username)
                text = describe(event)
                await db.add_history(event.chat.id, event.message_id, user.id, name, text, reply_name,
                                     reply_user_id=reply_user_id)
                await db.add_daily(event.chat.id, user.id, name, is_mat(event.text or event.caption or ""))
                # ответили «ахаха» на чужое сообщение: автору плюс в «самого смешного»
                if (rt and rt.from_user and not rt.from_user.is_bot and rt.from_user.id != user.id
                        and (is_laugh(event.text or "") or (event.sticker and event.sticker.emoji in LAUGH_EMOJI))):
                    await db.add_laugh(event.chat.id, rt.from_user.id, reply_name)
        except Exception:
            log.exception("Не удалось записать сообщение в базу")
        return await handler(event, data)
