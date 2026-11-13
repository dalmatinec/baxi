"""Кто-то вступил в чат, бота добавили или выгнали, группа стала супергруппой."""

import logging

from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated, Message

from bot import db, notify
from bot.middlewares import GROUPS
from bot.services import talk
from bot.textutil import esc, full_name

log = logging.getLogger(__name__)
router = Router(name="members")


@router.message(F.chat.type.in_(GROUPS), F.new_chat_members)
async def on_join(message: Message, bot: Bot, chat_row=None) -> None:
    if chat_row is None:
        return
    for user in message.new_chat_members:
        if user.id == bot.id or user.is_bot:
            continue
        name = full_name(user.first_name, user.last_name)
        await db.add_user_silently(message.chat.id, user.id, name, user.username or "")
        if not chat_row["greet"]:
            continue
        try:
            async with talk.chat_lock(message.chat.id):
                await talk.greet(bot, chat_row, user.id, name, thread=talk.thread_of(message))
        except Exception:
            log.exception("Не получилось поздороваться в чате %s", message.chat.id)


@router.message(F.migrate_to_chat_id)
async def on_migrate(message: Message) -> None:
    await db.migrate_chat(message.chat.id, message.migrate_to_chat_id)


@router.my_chat_member(F.chat.type.in_(GROUPS))
async def on_my_status(update: ChatMemberUpdated, bot: Bot) -> None:
    status = update.new_chat_member.status
    title = update.chat.title or str(update.chat.id)
    if status in ("left", "kicked"):
        if await db.get_chat(update.chat.id):
            await db.update_chat(update.chat.id, active=0)
        await notify.owners(bot, f"🚪 Меня убрали из чата «{esc(title)}»")
        return
    old = update.old_chat_member.status
    if old in ("left", "kicked"):
        await db.ensure_chat(update.chat.id, update.chat.title or "")
        await notify.owners(
            bot,
            f"👋 Меня добавили в чат «{esc(title)}».\n\n"
            "Настроить имя, характер и тему чата: /admin → Чаты.\n"
            "Чтобы я видел все сообщения, в @BotFather отключи Privacy Mode "
            "(Bot Settings → Group Privacy → Turn off) или сделай меня админом.")
