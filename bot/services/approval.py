"""Одобрение чатов и аренда.
Бота добавил владелец: работает сразу. Добавил кто-то другой: бот молчит и шлёт владельцу заявку
с кнопками. Нет ответа за APPROVAL_HOURS часов: бот сам выходит. Аренда: за 3 дня до конца
предупреждает, в конце срока выходит."""

import logging
import time
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import config, db, notify
from bot.services.out import say
from bot.textutil import esc

log = logging.getLogger(__name__)

RENT_DAYS = 30
WARN_BEFORE = 3 * 86400


def approval_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Разрешить", callback_data=f"ap:ok:{chat_id}", style="success"),
         InlineKeyboardButton(text="🚫 Выйти", callback_data=f"ap:no:{chat_id}", style="danger")],
        [InlineKeyboardButton(text=f"📅 Аренда {RENT_DAYS} дней", callback_data=f"ap:rent:{chat_id}",
                              style="primary")],
    ])


def until_text(ts: float) -> str:
    return datetime.fromtimestamp(ts, config.TZ).strftime("%d.%m.%Y")


async def request(bot: Bot, chat_id: int, title: str, added_by: int = 0, added_name: str = "") -> None:
    """Вызывается, когда бот оказался в новом чате. Повторно заявку не шлёт."""
    chat = await db.get_chat(chat_id) or await db.ensure_chat(chat_id, title)
    if chat["approved"]:
        return
    if added_by and added_by in config.OWNER_IDS:
        if not await approve(bot, chat_id, announce=False):
            return
        await notify.owners(bot, f"👋 Ты добавил меня в «{esc(title)}», я уже работаю.\n"
                                 "Настрой имя, характер и тему: /admin → Чаты.")
        return
    if chat["pending_since"]:
        return
    await db.update_chat(chat_id, pending_since=time.time(), added_by=added_by)
    members = "?"
    try:
        members = str(await bot.get_chat_member_count(chat_id))
    except Exception:
        pass
    me = await bot.me()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="💬 Написать мне", url=f"https://t.me/{me.username}?start=rent", style="primary")]])
    try:
        await say(bot, chat_id, "👋 привет! я работаю только в одобренных чатах. заявку уже отправил владельцу, "
                                f"если за {config.APPROVAL_HOURS} ч не одобрят, я сам выйду.\n\n"
                                "хотите меня в свой чат надолго? напишите мне в личку", markup=kb)
    except Exception as exc:
        log.info("Не смог написать в новый чат %s: %s", chat_id, exc)
    who = f"{esc(added_name)} (<code>{added_by}</code>)" if added_by else "неизвестно (меня добавили, пока я спал)"
    for owner in config.OWNER_IDS:
        try:
            await bot.send_message(owner, f"🔔 <b>Заявка: меня добавили в чат</b>\n\n"
                                          f"Чат: <b>{esc(title)}</b>\nУчастников: {members}\nДобавил: {who}\n\n"
                                          f"Без ответа выйду через {config.APPROVAL_HOURS} ч.",
                                   parse_mode="HTML", reply_markup=approval_kb(chat_id))
        except Exception as exc:
            log.info("Владелец %s не получил заявку: %s", owner, exc)


async def approve(bot: Bot, chat_id: int, rent_days: int = 0, announce: bool = True) -> bool:
    chat = await db.get_chat(chat_id)
    if chat is None:
        return False
    from bot.services import license
    limit = license.chat_limit()
    if limit and not chat["approved"] and len(await db.list_chats()) >= limit:
        await notify.owners(bot, f"⚠️ По тарифу можно {limit} чатов, лимит занят. Из «{esc(chat['title'])}» выхожу. "
                                 "Чтобы добавить больше чатов, смени тариф.")
        await leave(bot, chat_id, "у этого бота закончился лимит чатов, ухожу 👋")
        return False
    rent_until = 0.0
    if rent_days:
        start = max(time.time(), chat["rent_until"] or 0)
        rent_until = start + rent_days * 86400
    await db.update_chat(chat_id, approved=1, pending_since=0, rent_until=rent_until, rent_warned=0)
    if announce:
        text = f"✅ меня одобрили, всем привет! зовите меня {esc(chat['bot_name'])}. что умею: /games"
        if rent_until:
            text += f"\n\n📅 аренда до {until_text(rent_until)}"
        try:
            await say(bot, chat_id, text)
        except Exception:
            pass
    return True


async def leave(bot: Bot, chat_id: int, reason: str = "") -> None:
    if reason:
        try:
            await say(bot, chat_id, reason)
        except Exception:
            pass
    try:
        await bot.leave_chat(chat_id)
    except Exception as exc:
        log.info("Не вышел из чата %s: %s", chat_id, exc)
    await db.update_chat(chat_id, active=0, approved=0, pending_since=0)


async def tick(bot: Bot) -> None:
    now = time.time()
    for chat in await db.pending_chats():
        if now - chat["pending_since"] > config.APPROVAL_HOURS * 3600:
            await leave(bot, chat["chat_id"], "заявку не одобрили, ухожу. всем пока 👋")
            await notify.owners(bot, f"🚪 Вышел из «{esc(chat['title'])}»: заявку не одобрили вовремя")
    for chat in await db.list_chats():
        until = chat["rent_until"]
        if not until:
            continue
        if now >= until:
            await leave(bot, chat["chat_id"], "📅 аренда бота закончилась, ухожу. продлить: напишите мне в личку")
            await notify.owners(bot, f"📅 Аренда в «{esc(chat['title'])}» закончилась, я вышел")
        elif until - now < WARN_BEFORE and not chat["rent_warned"]:
            await db.update_chat(chat["chat_id"], rent_warned=1)
            try:
                await say(bot, chat["chat_id"], f"📅 аренда бота заканчивается {until_text(until)}. "
                                                "чтобы я остался, продлите: напишите мне в личку")
            except Exception:
                pass
            await notify.owners(bot, f"📅 В «{esc(chat['title'])}» аренда кончается {until_text(until)}")
