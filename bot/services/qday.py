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
    ai.CURRENT_CHAT.set(chat)
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
    """Оживить чат: днём, если в чате тихо дольше заданного (10-60 минут), бот вкидывает что-то одно:
    фразу из «Оживить чат», вопрос из базы или зовёт на викторину. Один раз на каждую тишину."""
    import random
    import time
    now = datetime.now(config.TZ)
    if not 10 <= now.hour < 23:
        return
    t = time.time()
    for chat in await db.list_chats():
        minutes = chat["revive"]
        if not minutes or chat["quiet_until"] > t:
            continue
        last = await db.last_message_ts(chat["chat_id"])
        if not last or not minutes * 60 < t - last < 12 * 3600 or chat["last_revive"] > last:
            continue  # ещё не тихо, давно мёртвый чат или в эту тишину уже оживляли
        await db.update_chat(chat["chat_id"], last_revive=t)
        roll = random.random()
        if roll < 0.2 and chat["games"] and chat["quiz"]:
            text = "скучно сидим... кто за викторину? пишите /quiz 🧠"
        elif roll < 0.4:
            text = "❓ " + (await db.random_phrase("qday") or "как у кого день?")
        else:
            text = await db.random_phrase("quiet") or "чего притихли? 👀"
        try:
            await say(bot, chat["chat_id"], esc(text))
        except Exception as exc:
            log.info("Оживить чат %s не вышло: %s", chat["chat_id"], exc)
