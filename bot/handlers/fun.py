"""Репутация (+/спасибо ответом), запись дня рождения, реакции на сообщения,
кнопки «как вам пара» и викторины."""

import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, MessageReactionCountUpdated, MessageReactionUpdated

from bot import db
from bot.middlewares import GROUPS, real_reply
from bot.services import daily, quiz
from bot.services.out import say
from bot.textutil import esc, full_name, human_date, mention, parse_birthday, rep_delta

router = Router(name="fun")




async def rep_filter(message: Message, chat_row=None, user_row=None) -> dict | bool:
    if chat_row is None or user_row is None or not chat_row["rep"]:
        return False
    rt = real_reply(message)
    if not rt or not rt.from_user or rt.from_user.is_bot or rt.from_user.id == message.from_user.id:
        return False
    delta = rep_delta(message.text or "")
    return {"delta": delta, "target": rt.from_user} if delta else False


@router.message(F.chat.type.in_(GROUPS), F.text, rep_filter)
async def on_rep(message: Message, bot: Bot, delta: int, target, user_row) -> None:
    chat_id = message.chat.id
    if not await db.rep_allowed(chat_id, message.from_user.id, target.id, time.time()):
        return  # уже давал этому человеку в последний час: молча пропускаем
    points = await db.rep_change(chat_id, message.from_user.id, target.id, delta)
    name = full_name(target.first_name, target.last_name)
    place = await db.rep_place(chat_id, target.id)
    from bot.services import texts
    html = await texts.render("tpl_rep_plus" if delta > 0 else "tpl_rep_minus", кому=mention(target.id, name),
                              от=esc(user_row["name"]), сколько=points, место=place)
    await say(bot, chat_id, html, reply_to=message)


async def bday_filter(message: Message, chat_row=None, user_row=None) -> dict | bool:
    if chat_row is None or user_row is None or not chat_row["bday"]:
        return False
    mmdd = parse_birthday(message.text or "")
    return {"mmdd": mmdd} if mmdd else False


@router.message(F.chat.type.in_(GROUPS), F.text, bday_filter)
async def on_bday(message: Message, bot: Bot, mmdd: str) -> None:
    await db.set_birthday(message.chat.id, message.from_user.id, mmdd)
    await say(bot, message.chat.id, f"🎂 записал, {human_date(mmdd)}. в этот день поздравлю всем чатом",
              reply_to=message)


@router.message_reaction()
async def on_reaction(update: MessageReactionUpdated) -> None:
    delta = len(update.new_reaction or []) - len(update.old_reaction or [])
    if delta:
        await db.add_reaction(update.chat.id, update.message_id, delta=delta)


@router.message_reaction_count()
async def on_reaction_count(update: MessageReactionCountUpdated) -> None:
    total = sum(r.total_count for r in update.reactions or [])
    await db.add_reaction(update.chat.id, update.message_id, total=total)


@router.callback_query(F.data.startswith("pp:"))
async def on_pair_vote(cb: CallbackQuery) -> None:
    await daily.on_pair_vote(cb)


@router.callback_query(F.data.startswith("qz:"))
async def on_quiz_answer(cb: CallbackQuery) -> None:
    await quiz.on_answer(cb)
