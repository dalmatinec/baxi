"""Команды в чате: «итоги» (любой, раз в час на чат; админам без ограничений),
«пара» и «сводка» (только админы чата и владельцы бота)."""

import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import brain, db
from bot.middlewares import GROUPS
from bot.services import caller, daily, fun, perms, stars, talk
from bot.services.out import say

log = logging.getLogger(__name__)
router = Router(name="commands")


async def command_filter(message: Message, chat_row=None) -> dict | bool:
    if chat_row is None:
        return False
    name = brain.detect_command(message.text or "")
    return {"command": name} if name else False


@router.message(F.chat.type.in_(GROUPS), F.text, command_filter)
async def on_command(message: Message, bot: Bot, command: str, chat_row) -> None:
    chat_id = message.chat.id
    admin = await perms.is_admin(bot, message)
    try:
        if command == "results":
            await _results(bot, message, chat_row, admin)
        elif command == "settings":
            if not admin:
                await say(bot, chat_id, "настраивать меня могут админы чата", reply_to=message)
                return
            me = await bot.me()
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                text="⚙️ Открыть настройки", url=f"https://t.me/{me.username}?start=mc{chat_id}", style="primary")]])
            await say(bot, chat_id, "настройки этого чата в личке 👇", reply_to=message, markup=kb)
        elif command == "pair":
            await _pair(bot, message, chat_row, admin)
        elif command in ("quiet", "talk", "call", "stopcall"):
            await _admin_tools(bot, message, chat_row, command, admin)
        elif command == "joke":
            async with talk.chat_lock(chat_id):
                await fun.joke(bot, chat_row, message, message.from_user.first_name or "друг")
        elif command == "roast":
            user_row = await db.get_user(chat_id, message.from_user.id)
            if user_row:
                async with talk.chat_lock(chat_id):
                    await fun.roast(bot, chat_row, message, user_row)
        elif command == "summary":
            if not admin:
                await say(bot, chat_id, "сводку делаю только по просьбе админов чата", reply_to=message)
                return
            async with talk.chat_lock(chat_id):
                await fun.summary(bot, chat_row, message, message.text or "")
    except Exception:
        log.exception("Команда %s в чате %s не выполнилась", command, chat_id)


async def _results(bot: Bot, message: Message, chat, admin: bool) -> None:
    chat_id = message.chat.id
    wait = daily.MANUAL_RESULTS_EVERY - (time.time() - chat["results_manual"])
    if not admin and wait > 0 and not await stars.is_vip(message.from_user.id):
        minutes = max(1, round(wait / 60))
        await say(bot, chat_id, f"итоги уже подводили недавно, следующие можно через {minutes} мин",
                  reply_to=message)
        return
    await db.update_chat(chat_id, results_manual=time.time())
    async with talk.chat_lock(chat_id):
        posted = await daily.post_results(bot, chat, manual=True, reply_to=message)
    if not posted:
        await db.update_chat(chat_id, results_manual=chat["results_manual"])  # не засчитываем попытку
        await say(bot, chat_id, "сегодня тут почти тихо, итожить нечего", reply_to=message)


async def _pair(bot: Bot, message: Message, chat, admin: bool) -> None:
    if not admin:
        return  # «пара» обычное слово, обычным участникам молча не отвечаем
    chat_id = message.chat.id
    if await db.open_poll(chat_id):
        await say(bot, chat_id, "голосование за пару уже идёт, жми кнопки там", reply_to=message)
        return
    if await daily.start_pair_poll(bot, chat):
        await db.update_chat(chat_id, last_pairpoll=db.today())
    else:
        await say(bot, chat_id, "сегодня мало кто писал, не из кого выбрать пару", reply_to=message)


async def _admin_tools(bot: Bot, message: Message, chat, command: str, admin: bool) -> None:
    chat_id = message.chat.id
    if not admin:
        await say(bot, chat_id, "это только для админов чата", reply_to=message)
        return
    if command == "quiet":
        await db.update_chat(chat_id, quiet_until=time.time() + 3600)
        await say(bot, chat_id, "ладно, на час притихну 🤐 позовёте по имени, отвечу", reply_to=message)
    elif command == "talk":
        await db.update_chat(chat_id, quiet_until=0)
        await say(bot, chat_id, "всё, я снова с вами 😎", reply_to=message)
    elif command == "stopcall":
        stopped = caller.stop(chat_id)
        await say(bot, chat_id, "ок, больше не зову" if stopped else "я и так никого не зову", reply_to=message)
    else:
        n = await caller.start(bot, chat, message, starter=message.from_user.id if message.from_user else 0)
        if n == -1:
            await say(bot, chat_id, "уже зову, подожди. остановить: /stopcall", reply_to=message)
        elif n == 0:
            await say(bot, chat_id, "некого звать: я ещё не видел тут людей по этому списку. настроить: /settings",
                      reply_to=message)
