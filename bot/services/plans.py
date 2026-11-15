"""Тарифы чатов: пробный, бесплатный, платный.

  🎁 пробный   добавили бота: сразу работает всё, TRIAL_DAYS дней, без ожидания одобрения
               (если выполнены условия ниже, иначе заявка владельцу как раньше)
  🆓 бесплатный после пробного или аренды бот не уходит: игры, фразы, итоги, репутация, уровни работают,
               а нейросеть выключена (или маленькая квота в день, если владелец её задал). Расход около нуля.
               1-2 раза в день бот напоминает, что есть платная версия.
  💳 платный    аренда оплачена или владелец разрешил навсегда: всё без ограничений.

Настройки владельца лежат в kv и меняются в /admin → Настройки → Пробный и бесплатный."""

import logging
import random
import time
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import ai, config, db
from bot.services.out import say
from bot.textutil import esc, mention

log = logging.getLogger(__name__)

# значения по умолчанию, владелец меняет их в админке
DEFAULTS = {
    "max_trials": 10,        # сколько чатов одновременно может быть на пробном
    "min_members": 10,       # пробный только для групп от стольких участников, мелкие сразу на бесплатный
    "free_ai": 0,            # ответов нейросети в день для бесплатного чата (0: только фразы)
    "nudges": 1,             # напоминаний о платной версии в день в бесплатном чате
    "free_persona": "",      # общий характер для бесплатных чатов ('' значит характер чата как есть)
}
SETTINGS: dict = dict(DEFAULTS)
_used: dict[tuple[int, str], int] = {}     # (чат, день) → сколько ответов ИИ уже дали бесплатному чату

NUDGES = [
    "💡 {who}, это бесплатная версия: без нейросети я отвечаю заготовками. С платной болтаю как живой, "
    "итоги дня картинками, зазывала, триггеры и викторины.",
    "🎁 {who}, хотите, чтобы я снова был умным? Подключите платную версию, и я вернусь во всей красе 😎",
    "🤖 {who}, сейчас я на бесплатном тарифе и отвечаю фразами. Платная версия: живые ответы, викторины и "
    "всё остальное.",
]


async def load() -> None:
    for key, default in DEFAULTS.items():
        raw = await db.kv_get(f"plan_{key}")
        SETTINGS[key] = (type(default)(raw) if raw != "" else default) if raw is not None else default


async def set_value(key: str, value) -> None:
    SETTINGS[key] = value
    await db.kv_set(f"plan_{key}", str(value))


def is_free(chat) -> bool:
    return bool(chat and chat["free"])


def status(chat) -> str:
    if is_free(chat):
        return "🆓 бесплатный"
    if chat["rent_until"]:
        return "🎁 пробный" if chat["trial"] else "💳 платный"
    return "♾ без срока"


def gate(chat) -> bool:
    """Можно ли нейросети отвечать в этом чате прямо сейчас (для бесплатных: квота в день)."""
    if not is_free(chat):
        return True
    quota = int(SETTINGS["free_ai"] or 0)
    if quota <= 0:
        return False
    key = (chat["chat_id"], datetime.now(config.TZ).strftime("%Y-%m-%d"))
    if _used.get(key, 0) >= quota:
        return False
    _used[key] = _used.get(key, 0) + 1
    if len(_used) > 5000:
        _used.clear()
    return True


ai.gate = gate  # ai.chat спрашивает разрешение для чата из ai.CURRENT_CHAT


def persona(chat) -> str:
    """Общий характер для бесплатных чатов, если владелец его задал."""
    return SETTINGS["free_persona"] if is_free(chat) and SETTINGS["free_persona"] else chat["persona"]


async def trial_check(chat, added_by: int, members: int) -> str:
    """Можно ли сразу дать пробный. Возвращает '' или причину, почему нет (тогда решает владелец)."""
    if chat["trial_used"]:
        return "этот чат уже был на пробном"
    if members and members < int(SETTINGS["min_members"]):
        return f"в группе меньше {SETTINGS['min_members']} участников"
    trials = [c for c in await db.list_chats() if c["trial"] and c["rent_until"] > time.time()]
    if len(trials) >= int(SETTINGS["max_trials"]):
        return f"сейчас уже {len(trials)} чатов на пробном, это предел"
    if added_by and added_by not in config.OWNER_IDS:
        used = [c for c in await db.list_chats(active_only=False)
                if c["added_by"] == added_by and c["trial_used"] and c["chat_id"] != chat["chat_id"]]
        if used:
            return "этот человек уже брал пробный в другом чате"
    return ""


async def to_free(bot: Bot, chat, reason: str) -> None:
    """Пробный или аренда кончились: бот остаётся на бесплатном тарифе, а не уходит."""
    await db.update_chat(chat["chat_id"], free=1, rent_until=0, trial=0, rent_warned=0)
    me = await bot.me()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="💳 Подключить платную", url=f"https://t.me/{me.username}?start=rent", style="success")]])
    try:
        await say(bot, chat["chat_id"], f"⏳ {esc(reason)}. Я остаюсь с вами на бесплатной версии: игры, итоги и "
                                        "репутация работают, а вместо нейросети отвечаю заготовками.", markup=kb)
    except Exception:
        pass


async def tick(bot: Bot) -> None:
    """Раз в N часов днём напоминает бесплатным чатам про платную версию."""
    per_day = int(SETTINGS["nudges"] or 0)
    now = datetime.now(config.TZ)
    if per_day <= 0 or not 13 <= now.hour < 21:
        return
    gap = 24 * 3600 / per_day - 3600
    t = time.time()
    me = None
    for chat in await db.list_chats():
        if not is_free(chat) or t - chat["last_nudge"] < gap:
            continue
        if not (await db.last_message_ts(chat["chat_id"])) > t - 6 * 3600:
            continue  # в тихий чат не пишем
        await db.update_chat(chat["chat_id"], last_nudge=t)
        me = me or await bot.me()
        who_id = chat["added_by"]
        who_name = (chat["added_name"] or "админ") if who_id else "админы"
        who = mention(who_id, who_name) if who_id else who_name
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="💳 Подключить платную", url=f"https://t.me/{me.username}?start=rent", style="success")]])
        try:
            await say(bot, chat["chat_id"], random.choice(NUDGES).replace("{who}", who), markup=kb)
        except Exception as exc:
            log.info("Напоминание в %s не ушло: %s", chat["chat_id"], exc)
