"""Что тут было (выжимка с номинациями), шутки и прожарка. Всё по обращению к боту."""

import logging
import random
import re
import time

from aiogram import Bot
from aiogram.types import Message

from bot import ai, db, nominations, prompts
from bot.nominations import Nominees
from bot.services import talk
from bot.services.out import say
from bot.textutil import MSGS, REACTS, esc, mention, plural

log = logging.getLogger(__name__)

FALLBACK_JOKES = [
    "купил книгу как пережить что угодно. на обложке мелким шрифтом: посмертное издание",
    "дед всегда говорил, что жизнь коротка. особенно громко он это говорил, когда переходил дорогу на красный",
    "врач сказал мне меньше нервничать. сказал это, глядя в мои анализы, и сам занервничал",
    "мой оптимизм как парашют: если не раскрылся, жаловаться уже некому",
]


def funny_line(p: nominations.Person) -> str:
    parts = []
    if p.reacts:
        parts.append(f"{p.reacts} {plural(p.reacts, REACTS)}")
    if p.laughs:
        parts.append(f"рассмешил чат {p.laughs} раз")
    return ", ".join(parts)


def nominees_html(n: Nominees) -> list[str]:
    lines = []
    if n.talker:
        lines.append(f"🗣 <b>Болтун:</b> {mention(n.talker.user_id, n.talker.name)}, "
                     f"{n.talker.msgs} {plural(n.talker.msgs, MSGS)}")
    if n.funny:
        lines.append(f"😂 <b>Самый смешной:</b> {mention(n.funny.user_id, n.funny.name)}, {funny_line(n.funny)}")
    if n.swearer:
        lines.append(f"🤬 <b>Матершинник:</b> {mention(n.swearer.user_id, n.swearer.name)}, "
                     f"{n.swearer.mat_pct}% сообщений с матом")
    return lines


def rude_line(data: dict | None) -> str | None:
    if not data:
        return None
    rude = str(data.get("rude") or "").strip()
    why = str(data.get("rude_why") or "").strip()
    if not rude:
        return None
    return f"😤 <b>Самый грубый:</b> {esc(rude)}" + (f", {esc(why)}" if why else "")


async def _names(chat_id: int, rows) -> dict[int, str]:
    ids = {r["user_id"] for r in rows} | {r["reply_user_id"] for r in rows if r["reply_user_id"]}
    return {u["user_id"]: u["name"] for u in await db.users_by_ids(chat_id, list(ids))}


async def summary(bot: Bot, chat, message: Message, text: str) -> None:
    chat_id = chat["chat_id"]
    secs, label = nominations.parse_period(text)
    since = time.time() - secs
    rows = await db.history_since(chat_id, since)
    humans = [r for r in rows if not r["is_bot"]]
    if len(humans) < 5:
        await say(bot, chat_id, f"{label} тут почти никто не писал, пересказывать нечего", reply_to=message)
        return
    await talk.typing(bot, chat_id, "...")
    people = nominations.people_from_history(rows, await db.reacts_by_user(chat_id, since), await _names(chat_id, rows))
    nom = nominations.nominate(people)
    system, _ = await talk.context(chat)
    data = await ai.chat_json([{"role": "system", "content": system},
                               {"role": "user", "content": prompts.summary_task(prompts.transcript(rows), label)}],
                              max_tokens=500)
    lines = [f"📋 <b>Что было {label}</b> · {nom.total} {plural(nom.total, MSGS)}", ""]
    lines += nominees_html(nom)
    rude = rude_line(data)
    if rude:
        lines.append(rude)
    short_text = str((data or {}).get("summary") or "").strip()
    lines += ["", "<b>Коротко</b>", esc(prompts.clean_reply(short_text, chat["bot_name"], limit=900))] if short_text \
        else ["", "<i>пересказать словами сейчас не выйдет, но цифры выше честные</i>"]
    sent = await say(bot, chat_id, "\n".join(lines), reply_to=message)
    await talk.remember_self(bot, chat, sent, "[выжимка чата]")


async def joke(bot: Bot, chat, message: Message, author: str) -> None:
    system, _ = await talk.context(chat)
    answer = await ai.chat([{"role": "system", "content": system},
                            {"role": "user", "content": prompts.joke_task(author)}],
                           max_tokens=220, temperature=1.2)
    text = prompts.clean_reply(answer or "", chat["bot_name"]) or random.choice(FALLBACK_JOKES)
    await talk.send_text(bot, chat, esc(text), text, reply_to=message, reply_name=author)


_ROAST_TAIL = re.compile(r"(?:прожар\w*|прожги|зажарь|обосри|разнеси)\s+@?([\wёЁ]+)", re.I)


async def roast_target(bot: Bot, chat_id: int, message: Message):
    """Кого жарить: на чьё сообщение ответили, кого отметили, кого назвали по имени. Иначе самого просящего."""
    rt = message.reply_to_message
    if rt and rt.from_user and not rt.from_user.is_bot:
        return await db.get_user(chat_id, rt.from_user.id)
    for ent in message.entities or []:
        if ent.type == "text_mention" and ent.user:
            return await db.get_user(chat_id, ent.user.id)
        if ent.type == "mention":
            username = (message.text or "")[ent.offset + 1: ent.offset + ent.length]
            me = await bot.me()
            if username.lower() != (me.username or "").lower():
                found = await db.find_user(chat_id, username)
                if found:
                    return found
    m = _ROAST_TAIL.search(message.text or "")
    if m and m.group(1).lower() not in ("его", "её", "ее", "меня", "себя"):
        found = await db.find_user(chat_id, m.group(1))
        if found:
            return found
    return None


async def roast(bot: Bot, chat, message: Message, author_row) -> None:
    chat_id = chat["chat_id"]
    target = await roast_target(bot, chat_id, message) or author_row
    perks = await db.get_perks(target["user_id"])
    if perks and perks["shield_until"] > time.time():
        await say(bot, chat_id, f"у {esc(target['name'])} щит от прожарки 🛡, не пробить", reply_to=message)
        return
    stats_row = [r for r in await db.daily_stats(chat_id, db.today()) if r["user_id"] == target["user_id"]]
    stats = ""
    if stats_row and stats_row[0]["msgs"]:
        s = stats_row[0]
        stats = (f"Сегодня написал {s['msgs']} {plural(s['msgs'], MSGS)}, "
                 f"мат в {round(s['mat'] * 100 / s['msgs'])}% из них.")
    messages = await db.user_messages(chat_id, target["user_id"], 30)
    system, _ = await talk.context(chat)
    answer = await ai.chat([{"role": "system", "content": system},
                            {"role": "user", "content": prompts.roast_task(target["name"], target["notes"],
                                                                           messages, stats)}],
                           max_tokens=320, temperature=1.1)
    text = prompts.clean_reply(answer or "", chat["bot_name"], limit=900)
    if not text:
        text = f"{target['name']}, тебя даже жарить жалко, ты и так подгорел"
    html = f"🔥 <b>Прожарка:</b> {mention(target['user_id'], target['name'])}\n\n{esc(text)}"
    await talk.typing(bot, chat_id, text)
    sent = await say(bot, chat_id, html, reply_to=message)
    await talk.remember_self(bot, chat, sent, text, author_row["name"])
