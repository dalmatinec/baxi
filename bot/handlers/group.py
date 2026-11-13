"""Обычные сообщения в группе: решаем, отвечать или нет, и чем."""

import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot import brain, db
from bot.middlewares import GROUPS, TRACKED, describe
from bot.services import fun, memory, quiz, talk

log = logging.getLogger(__name__)
router = Router(name="group")
spam_guard = brain.RateLimit(limit=5, window=60)


@router.message(F.chat.type.in_(GROUPS), F.content_type.in_(TRACKED))
async def on_message(message: Message, bot: Bot, chat_row=None, user_row=None) -> None:
    if chat_row is None or user_row is None:
        return  # другой бот, канал или аноним-админ: молчим
    chat_id = message.chat.id
    memory.maybe_update(chat_id, user_row)

    me = await bot.me()
    text = message.text or message.caption or ""
    rt = message.reply_to_message
    reply_to_bot = bool(rt and rt.from_user and rt.from_user.id == me.id)
    aliases = brain.parse_aliases(chat_row["bot_name"], chat_row["aliases"])
    addressed = brain.is_addressed(text, me.username or "", aliases, reply_to_bot)

    act = brain.decide(addressed, time.time(), chat_row["last_jump"], chat_row["cooldown"],
                       chat_row["chance"], chat_row["ai_share"])
    if act is brain.Act.NONE:
        return
    if act is brain.Act.AI_REPLY and not spam_guard.allow(chat_id, user_row["user_id"], time.time()):
        return  # человек долбит бота обращениями: молча пропускаем, ИИ не тратим

    lock = talk.chat_lock(chat_id)
    if act is not brain.Act.AI_REPLY:
        if lock.locked():
            return  # бот уже что-то пишет в этот чат, второй раз не влезаем
        await db.update_chat(chat_id, last_jump=time.time())

    author = user_row["name"]
    intent = brain.detect_intent(text) if act is brain.Act.AI_REPLY else None
    if intent == "quiz" and not chat_row["games"]:
        intent = None
    try:
        async with lock:
            if intent == "summary":
                await fun.summary(bot, chat_row, message, text)
            elif intent == "joke":
                await fun.joke(bot, chat_row, message, author)
            elif intent == "roast":
                await fun.roast(bot, chat_row, message, user_row)
            elif intent == "quiz":
                await quiz.start(bot, chat_row, message)
            elif act is brain.Act.PHRASE:
                await talk.phrase_answer(bot, chat_row, message, author)
            else:
                await talk.ai_answer(bot, chat_row, message, author, text or describe(message),
                                     jump=act is brain.Act.AI_JUMP)
    except Exception:
        log.exception("Не получилось ответить в чате %s", chat_id)

