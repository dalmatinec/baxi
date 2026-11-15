"""Вопрос дня: раз в день бот задаёт чату тему для обсуждения. Если нейросеть доступна, вопрос под тему
чата (1 запрос в день, копейки), иначе из базы фраз «Вопрос дня». В мёртвые чаты не пишет."""

import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot

from bot import ai, config, db
from bot.services import talk
from bot.services.out import say
from bot.textutil import esc

log = logging.getLogger(__name__)
HOUR = int(os.getenv("QDAY_HOUR", "12") or 12)
REVIVE_AFTER = 3 * 3600      # сколько тишины, чтобы бот попробовал оживить чат
REVIVE_EVERY = 6 * 3600      # и не чаще раза в 6 часов


def _task(topic: str):
    def make(history: str) -> str:
        return (f"Тема чата: {topic}. Последние сообщения:\n{history}\n\n"
                "Придумай один интересный вопрос дня, чтобы участники захотели ответить и поспорить. "
                "Лёгкий, без политики и религии, коротко, одним предложением, на ты ко всем. "
                "Напиши только сам вопрос.")
    return make


async def question(chat) -> str:
    if ai.enabled():
        try:
            q = await talk._ask(chat, _task(chat["topic"]))
            if q and len(q) < 300:
                return q
        except Exception:
            log.exception("Вопрос дня через ИИ не получился")
    return await db.random_phrase("qday") or "что сегодня было самым приятным за день?"


async def post(bot: Bot, chat) -> None:
    queue = [q for q in (chat["qday_queue"] or "").splitlines() if q.strip()]
    if queue:  # свой вопрос от админа чата идёт первым
        q = queue.pop(0).strip()
        await db.update_chat(chat["chat_id"], qday_queue="\n".join(queue))
    else:
        q = await question(chat)
    await say(bot, chat["chat_id"], f"❓ <b>Вопрос дня</b>\n\n{esc(q)}\n\n<i>пишите свои ответы 👇</i>")


async def tick(bot: Bot) -> None:
    now = datetime.now(config.TZ)
    if now.hour < HOUR:
        return
    today = now.strftime("%Y-%m-%d")
    recent = [today, (now - timedelta(days=1)).strftime("%Y-%m-%d")]
    for chat in await db.list_chats():
        if not chat["qday"] or chat["last_qday"] == today:
            continue
        await db.update_chat(chat["chat_id"], last_qday=today)
        if sum((await db.days_totals(chat["chat_id"], recent)).values()) < 5:
            continue  # чат почти мёртвый, не спамим
        try:
            await post(bot, chat)
        except Exception as exc:
            log.info("Вопрос дня в %s не отправился: %s", chat["chat_id"], exc)


async def revive_tick(bot: Bot) -> None:
    """Оживить чат: днём, если 3 часа тишины после живого разговора, бот пишет фразу из «Оживить чат»."""
    import time
    now = datetime.now(config.TZ)
    if not 11 <= now.hour < 22:
        return
    t = time.time()
    for chat in await db.list_chats():
        if not chat["revive"] or t - chat["last_revive"] < REVIVE_EVERY or chat["quiet_until"] > t:
            continue
        last = await db.last_message_ts(chat["chat_id"])
        if not last or not REVIVE_AFTER < t - last < 24 * 3600:
            continue
        await db.update_chat(chat["chat_id"], last_revive=t)
        phrase = await db.random_phrase("quiet")
        if phrase:
            try:
                await say(bot, chat["chat_id"], esc(phrase))
            except Exception as exc:
                log.info("Оживить чат %s не вышло: %s", chat["chat_id"], exc)
