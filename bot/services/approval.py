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
from bot.services import talk
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
        if not await approve(bot, chat_id):
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
        await talk.in_character(
            bot, chat_id,
            "Тебя только что добавили в этот чат, ты новенький. Поздоровайся со всеми в своём характере и скажи, "
            "что пока осматриваешься и скоро начнёшь общаться. 1-2 коротких предложения. Не используй слова "
            "бот, одобрение, заявка, модератор, владелец.",
            ["о, всем привет 👀 я тут новенький, пока осматриваюсь, скоро освоюсь и начну болтать",
             "здарова, чат! дайте мне минутку осмотреться, и я с вами 😎",
             "привет всем! я пока тихонько присмотрюсь к вам, скоро вольюсь в разговор"],
            markup=kb)
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
        await leave(bot, chat_id, "Тебе нужно уйти из этого чата: у хозяина закончился лимит чатов.")
        return False
    rent_until = 0.0
    if rent_days:
        start = max(time.time(), chat["rent_until"] or 0)
        rent_until = start + rent_days * 86400
    await db.update_chat(chat_id, approved=1, pending_since=0, rent_until=rent_until, rent_warned=0)
    if announce:
        tail = "🎲 что я умею: /games" + (f"\n📅 аренда до {until_text(rent_until)}" if rent_until else "")
        try:
            await talk.in_character(
                bot, chat_id,
                f"Тебя приняли в этот чат, теперь ты свой. Поздоровайся со всеми в своём характере и представься: "
                f"тебя зовут {chat['bot_name']}, тебя можно звать по имени. 1-2 коротких предложения.",
                [f"всем привет! я {chat['bot_name']}, теперь я с вами. зовите по имени, если что 😎",
                 f"ну всё, я официально в чате! меня зовут {chat['bot_name']}, будем знакомы",
                 f"здарова, народ! {chat['bot_name']} на связи, зовите, не стесняйтесь"],
                tail_html=tail)
        except Exception:
            pass
    return True


FAREWELLS = ["ладно, мне пора. всем пока, не скучайте 👋", "ну всё, ухожу по-английски... почти. пока, чат 👋",
             "было весело, но мне пора. всем добра ✌️"]


async def leave(bot: Bot, chat_id: int, reason: str = "", tail_html: str = "") -> None:
    """Выйти из чата. reason: ситуация для ИИ, чтобы попрощаться в образе. tail_html: служебная строка."""
    if reason:
        try:
            await talk.in_character(bot, chat_id, f"{reason} Попрощайся со всеми в своём характере, "
                                                  "одно короткое предложение.", FAREWELLS, tail_html=tail_html)
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
            await leave(bot, chat["chat_id"], "Тебе пора уйти из этого чата, остаться тебе не разрешили.")
            await notify.owners(bot, f"🚪 Вышел из «{esc(chat['title'])}»: заявку не одобрили вовремя")
    for chat in await db.list_chats():
        until = chat["rent_until"]
        if not until:
            continue
        if now >= until:
            await leave(bot, chat["chat_id"], "Тебе пора уйти из чата: закончился оплаченный срок.",
                        tail_html="📅 вернуть меня: напишите мне в личку → Добавить в чат → Оплатить аренду")
            await notify.owners(bot, f"📅 Аренда в «{esc(chat['title'])}» закончилась, я вышел")
        elif until - now < WARN_BEFORE and not chat["rent_warned"]:
            await db.update_chat(chat["chat_id"], rent_warned=1)
            try:
                await talk.in_character(
                    bot, chat["chat_id"],
                    "Через пару дней тебе придётся уйти из этого чата, если тебя не продлят. Скажи об этом в своём "
                    "характере, с юмором, и намекни, что продлить можно у тебя в личке. 1-2 предложения.",
                    ["эй, чат, через пару дней мне придётся уйти, если меня не продлят. не бросайте меня 🥺"],
                    tail_html=f"📅 срок до {until_text(until)}. продлить: личка бота → Добавить в чат → Оплатить аренду")
            except Exception:
                pass
            await notify.owners(bot, f"📅 В «{esc(chat['title'])}» аренда кончается {until_text(until)}")
