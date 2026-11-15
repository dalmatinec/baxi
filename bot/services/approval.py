"""Одобрение чатов и аренда.
Бота добавил владелец: работает сразу. Добавил кто-то другой: бот молчит и шлёт владельцу заявку
с кнопками. Нет ответа за APPROVAL_HOURS часов: бот сам выходит. Аренда: за 3 дня до конца
предупреждает, в конце срока выходит."""

import logging
import time
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import config, db, notify
from bot.services import talk
from bot.textutil import esc

log = logging.getLogger(__name__)

RENT_DAYS = 30
WARN_BEFORE = 3 * 86400


def approval_kb(chat_id: int, added_by: int = 0, username: str = "") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✅ Разрешить", callback_data=f"ap:ok:{chat_id}", style="success"),
         InlineKeyboardButton(text="🚫 Отказать", callback_data=f"ap:no:{chat_id}", style="danger")],
        [InlineKeyboardButton(text=f"📅 Аренда {RENT_DAYS} дн", callback_data=f"ap:rent:{chat_id}", style="primary"),
         InlineKeyboardButton(text=f"🎁 Пробные {config.TRIAL_DAYS} дня", callback_data=f"ap:trial:{chat_id}")],
    ]
    rows += contact_rows(added_by, username)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_rows(user_id: int, username: str = "") -> list[list[InlineKeyboardButton]]:
    """Кнопки связи с тем, кто добавил бота: через бота и напрямую (если есть юзернейм)."""
    if not user_id:
        return []
    row = [InlineKeyboardButton(text="✍️ Написать", callback_data=f"sup:{user_id}")]
    if username:
        row.append(InlineKeyboardButton(text=f"💬 @{username}", url=f"https://t.me/{username}"))
    return [row]


def adder_html(chat) -> str:
    """Кто добавил бота в чат, кликабельно, с юзернеймом и id."""
    uid = chat["added_by"]
    if not uid:
        return "неизвестно"
    name = esc(chat["added_name"] or "без имени")
    user = f" @{esc(chat['added_username'])}" if chat["added_username"] else ""
    return f'<a href="tg://user?id={uid}">{name}</a>{user} (<code>{uid}</code>)'


def until_text(ts: float) -> str:
    return datetime.fromtimestamp(ts, config.TZ).strftime("%d.%m.%Y")


async def request(bot: Bot, chat_id: int, title: str, added_by: int = 0, added_name: str = "",
                  added_username: str = "") -> None:
    """Вызывается, когда бот оказался в новом чате. Повторно заявку не шлёт."""
    chat = await db.get_chat(chat_id) or await db.ensure_chat(chat_id, title)
    if chat["approved"]:
        return
    if added_by and added_by in config.OWNER_IDS:
        if not await approve(bot, chat_id):
            return
        await notify.owners(bot, f"👋 Ты добавил меня в {esc(title)}, я уже работаю.\n"
                                 "Настрой имя, характер и тему: /admin → Чаты.")
        return
    if chat["pending_since"]:
        return
    await db.update_chat(chat_id, added_by=added_by, added_name=added_name, added_username=added_username)
    members = "?"
    try:
        members = str(await bot.get_chat_member_count(chat_id))
    except Exception:
        pass
    # пробный без ожидания, если выполнены условия; маленькие группы сразу на бесплатный
    from bot.services import plans
    chat = await db.get_chat(chat_id)
    why = await plans.trial_check(chat, added_by, int(members) if members.isdigit() else 0)
    if not why or why.startswith("в группе меньше"):
        trial = not why
        if not await approve(bot, chat_id, rent_days=config.TRIAL_DAYS if trial else 0, trial=trial):
            return
        if trial:
            await db.update_chat(chat_id, trial_used=1)
        else:
            await db.update_chat(chat_id, free=1)
        kind = f"🎁 пробный на {config.TRIAL_DAYS} дн." if trial else "🆓 бесплатный (маленькая группа)"
        await notify.owners(bot, f"➕ Новый чат: <b>{esc(title)}</b>, {members} участн.\nТариф: {kind}\n"
                                 f"Добавил: {adder_html(await db.get_chat(chat_id))}")
        return
    await db.update_chat(chat_id, pending_since=time.time())
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
    who = adder_html(await db.get_chat(chat_id)) if added_by else "неизвестно (меня добавили, пока я спал)"
    rights = await adder_rights(bot, chat_id, added_by) if added_by else ""
    kind = "открытая группа" if await _is_public(bot, chat_id) else "закрытая группа"
    await _tell_requested(bot, added_by, title)
    for owner in config.OWNER_IDS:
        try:
            await bot.send_message(owner, f"🔔 <b>Заявка</b>\n\n"
                                          f"Чат: <b>{esc(title)}</b>\n👥 {members} участников · {kind}\n"
                                          f"Добавил: {who}\n{rights}\n"
                                          f"Пробный автоматически не дал: {esc(why)}\n\n"
                                          f"Без ответа выйду через {config.APPROVAL_HOURS} ч.\n\n"
                                          "<i>Написать через бота можно, только если человек уже запускал бота "
                                          "в личке. Иначе пиши ему напрямую.</i>",
                                   parse_mode="HTML", reply_markup=approval_kb(chat_id, added_by, added_username))
        except Exception as exc:
            log.info("Владелец %s не получил заявку: %s", owner, exc)


async def adder_rights(bot: Bot, chat_id: int, user_id: int) -> str:
    """Какие права в чате у того, кто добавил бота."""
    try:
        m = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return "❔ права не известны"
    if m.status == "creator":
        return "✅ создатель чата"
    if m.status == "administrator":
        return ("✅ админ с правом назначать админов" if getattr(m, "can_promote_members", False)
                else "⚠️ админ без права назначать админов, настраивать бота не сможет")
    return "⚠️ обычный участник, не админ"


async def _is_public(bot: Bot, chat_id: int) -> bool:
    try:
        return bool((await bot.get_chat(chat_id)).username)
    except Exception:
        return False


async def _tell_requested(bot: Bot, user_id: int, title: str) -> None:
    """Тому, кто добавил: заявка ушла, напишу, когда одобрят."""
    if not user_id or user_id in config.OWNER_IDS:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🆘 Задать вопрос",
                                                                     callback_data="act:support:заявка")]])
    try:
        await bot.send_message(user_id, f"⏳ Заявка на <b>{esc(title)}</b> отправлена.\n"
                                        "Как только её одобрят, напишу сюда.", parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass  # человек ещё не запускал бота в личке


async def approve(bot: Bot, chat_id: int, rent_days: int = 0, announce: bool = True, trial: bool = False) -> bool:
    chat = await db.get_chat(chat_id)
    if chat is None:
        return False
    from bot.services import license
    limit = license.chat_limit()
    if limit and not chat["approved"] and len(await db.list_chats()) >= limit:
        await notify.owners(bot, f"⚠️ По тарифу можно {limit} чатов, лимит занят. Из {esc(chat['title'])} выхожу. "
                                 "Чтобы добавить больше чатов, смени тариф.")
        await leave(bot, chat_id, "Тебе нужно уйти из этого чата: у хозяина закончился лимит чатов.")
        return False
    rent_until = 0.0
    if rent_days:
        start = max(time.time(), chat["rent_until"] or 0)
        rent_until = start + rent_days * 86400
    await db.update_chat(chat_id, approved=1, pending_since=0, rent_until=rent_until, rent_warned=0,
                         trial=1 if trial else 0, free=0)
    if announce:
        period = "🎁 пробный период" if trial else "📅 аренда"
        tail = "🎲 что я умею: /games" + (f"\n{period} до {until_text(rent_until)}" if rent_until else "")
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
        await _tell_adder(bot, chat)
    return True


async def _tell_adder(bot: Bot, chat) -> None:
    """Тому, кто добавил бота, пишем в личку: бот работает, настроить можно в «Мои чаты»."""
    adder = chat["added_by"]
    if not adder or adder in config.OWNER_IDS:
        return
    from bot.handlers.chatadmin import can_manage
    chat = await db.get_chat(chat["chat_id"])
    text = f"✅ <b>Я работаю в {esc(chat['title'])}!</b>\n\n"
    if chat["rent_until"]:
        text += f"{'🎁 Пробный период' if chat['trial'] else '📅 Аренда'} до {until_text(chat['rent_until'])}.\n\n"
    if await can_manage(bot, adder, chat["chat_id"]):
        text += "Давай настроим меня под твой чат, это займёт минуту."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="⚙️ Настроить за минуту", callback_data=f"wz:s:{chat['chat_id']}", style="primary")]])
    else:
        text += ("Настраивать его в чате могут создатель чата и админы с правом назначать админов. "
                 "Им нужно написать мне в личку → ⚙️ Мои чаты.")
        kb = None
    try:
        await bot.send_message(adder, text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass  # человек ещё не запускал бота в личке


async def bot_present(bot: Bot, chat_id: int) -> bool | None:
    """Есть ли бот в чате. False: точно нет (чат удалён, бота выгнали). None: не понятно (нет связи)."""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    except Exception:
        return None
    return me.status not in ("left", "kicked")


FAREWELLS = ["ладно, мне пора. всем пока, не скучайте 👋", "ну всё, ухожу по-английски... почти. пока, чат 👋",
             "было весело, но мне пора. всем добра ✌️"]


async def leave(bot: Bot, chat_id: int, reason: str = "", tail_html: str = "") -> None:
    """Выйти из чата. reason: ситуация для ИИ, чтобы попрощаться в образе. tail_html: служебная строка.
    Если чата уже нет или бота оттуда убрали, просто отмечаем это в базе."""
    if await bot_present(bot, chat_id) is False:
        await db.update_chat(chat_id, active=0, approved=0, pending_since=0)
        return
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
            await notify.owners(bot, f"🚪 Вышел из {esc(chat['title'])}: заявку не одобрили вовремя")
    for chat in await db.list_chats():
        until = chat["rent_until"]
        if not until:
            continue
        if now >= until:
            from bot.services import plans
            kind = "Пробный период закончился" if chat["trial"] else "Оплаченный срок закончился"
            await plans.to_free(bot, chat, kind)
            await notify.owners(bot, f"📅 {kind} в {esc(chat['title'])}, чат перешёл на бесплатный")
        elif until - now < (86400 if chat["trial"] else WARN_BEFORE) and not chat["rent_warned"]:
            await db.update_chat(chat["chat_id"], rent_warned=1)
            try:
                await talk.in_character(
                    bot, chat["chat_id"],
                    "Скоро тебе придётся уйти из этого чата, если тебя не продлят. Скажи об этом в своём "
                    "характере, с юмором, и намекни, что продлить можно у тебя в личке. 1-2 предложения.",
                    ["эй, чат, скоро мне придётся уйти, если меня не продлят. не бросайте меня 🥺"],
                    tail_html=f"📅 срок до {until_text(until)}. продлить: личка бота → Добавить в чат → Оплатить аренду")
            except Exception:
                pass
            await notify.owners(bot, f"📅 В {esc(chat['title'])} аренда кончается {until_text(until)}")
            if chat["added_by"] and chat["added_by"] not in config.OWNER_IDS:
                try:
                    await bot.send_message(
                        chat["added_by"], f"📅 {'Пробный период' if chat['trial'] else 'Аренда'} в "
                                          f"<b>{esc(chat['title'])}</b> заканчивается {until_text(until)}. "
                                          "Чтобы я остался, продли аренду 👇", parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                            text="💳 Продлить аренду", callback_data=f"rt:{chat['chat_id']}", style="success")]]))
                except Exception:
                    pass
