"""Профиль участника в чате: /profile, /me, «профиль», «мой профиль». Ответом на сообщение: профиль того человека.

Текст берётся из шаблона «profile» (texts.py): админ чата может поменять его под себя, добавить картинку
и кнопки. Здесь только собираются значения подстановок."""

import datetime
import time

from aiogram import Bot
from aiogram.types import User

from bot import config, db
from bot.textutil import esc, full_name, mention


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _date(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, config.TZ).strftime("%d.%m.%Y") if ts else "неизвестно"


def last_active_text(ts: float) -> str:
    if not ts:
        return "давно"
    dt = datetime.datetime.fromtimestamp(ts, config.TZ)
    today = datetime.datetime.now(config.TZ).date()
    if time.time() - ts < 120:
        return "только что"
    if dt.date() == today:
        return f"сегодня в {dt:%H:%M}"
    if dt.date() == today - datetime.timedelta(days=1):
        return f"вчера в {dt:%H:%M}"
    return dt.strftime("%d.%m.%Y %H:%M")


async def role(bot: Bot, chat_id: int, user_id: int) -> str:
    """Роль в чате: Создатель, Администратор или Участник, плюс VIP и Топ, если есть."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        status = member.status
    except Exception:
        status = "member"
    text = {"creator": "Создатель", "administrator": "Администратор"}.get(status, "Участник")
    perks = await db.get_perks(user_id)
    if perks and perks["vip_until"] > time.time():
        text += " · VIP"
    try:
        from bot.games import tops
        if await tops.is_top(chat_id, user_id):
            text += " · Топ"
    except Exception:
        pass
    return text


async def values(bot: Bot, chat_id: int, user: User) -> dict:
    """Все подстановки шаблона профиля."""
    from bot.economy import catalog, store
    from bot.services import guardlink
    name = full_name(user.first_name, user.last_name)
    row = await db.get_user(chat_id, user.id)
    rank = await store.chat_rank(chat_id, user.id, name)
    wallet = await store.wallet(user.id, name)
    st = await guardlink.state(chat_id, user.id)
    warns = f"{st['warns']}/{st['warn_limit']}" if st and st["warns"] > 0 else "нет"
    debt = "нет"
    try:
        from bot.games import debts
        debt = await debts.summary(chat_id, user.id) or "нет"
    except Exception:
        pass
    return {
        "mention": mention(user.id, name),
        "name": esc(name),
        "username": f"@{esc(user.username)}" if user.username else "нет",
        "user_id": f"<code>{user.id}</code>",
        "status": await role(bot, chat_id, user.id),
        "join_date": _date(row["first_seen"] if row else 0),
        "messages": _num(row["msg_count"] if row else 0),
        "messages_24h": _num(await db.messages_24h(chat_id, user.id)),
        "last_active": last_active_text(row["last_seen"] if row else 0),
        "reputation": str(await db.rep_get(chat_id, user.id)),
        "rank": f"{rank['level']} · {catalog.title_for(rank['level'])}",
        "achievements": "пока нет",
        "warnings": warns,
        "balance": f"{_num(wallet['coins'])} 🪙",
        "debt": debt,
    }


async def send(bot: Bot, chat_id: int, user: User, reply_to=None, extra=None):
    from bot.services import texts
    return await texts.send(bot, chat_id, "profile", reply_to=reply_to, extra=extra, **await values(bot, chat_id, user))
