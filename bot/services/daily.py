"""Что бот делает сам по расписанию: «чат, как вам пара?», итоги дня вечером,
поздравления с днём рождения. Проверка раз в минуту."""

import asyncio
import logging
import random
import time
from datetime import datetime

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot import ai, config, db, games, nominations, prompts
from bot.services import approval, license, stars, talk
from bot.services.fun import nominees_html, rude_line
from bot.services.out import say
from bot.textutil import MSGS, REACTS, esc, human_date, mention, plural

log = logging.getLogger(__name__)

CHECK_EVERY = 60
POLL_HOURS = (13, 21)       # когда бот может спросить «как вам пара»
POLL_CHANCE = 1 / 120       # шанс в каждую минуту, когда чат живой
POLL_ACTIVE_MSGS = 15       # «живой» чат: столько сообщений за последний час
POLL_DURATION = 3600        # голосование длится час
RESULTS_MIN_MSGS = 20       # тихий день без итогов
MANUAL_MIN_MSGS = 5         # итоги по команде можно и при малом числе сообщений
MANUAL_RESULTS_EVERY = 3600 # обычным участникам «итоги» не чаще раза в час на чат
BDAY_HOUR = 10

DAY_WORDS = [
    "сегодня чат ни разу не обсудил ничего полезного. стабильность, уважаю",
    "день прошёл, а смысла в переписке так и не появилось. до завтра",
    "сегодня вы были невыносимы. завтра повторим",
]
BDAY_TEMPLATES = [
    "{name}, с днюхой! пусть всё будет чётко, а чат перестанет тебя бесить. чат, поздравляем!",
    "сегодня день рождения у {name}! расти большим, не будь лапшой. чат, накидайте поздравлений",
]


def midnight_ts() -> float:
    now = datetime.now(config.TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


# ---------- «как вам пара» ----------

def poll_markup(poll_id: int, yes: int, no: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"💘 Огонь · {yes}", callback_data=f"pp:{poll_id}:1"),
        InlineKeyboardButton(text=f"🙅 Не верю · {no}", callback_data=f"pp:{poll_id}:0"),
    ]])


async def start_pair_poll(bot: Bot, chat) -> bool:
    chat_id = chat["chat_id"]
    since = midnight_ts()
    pair = await db.top_reply_pair(chat_id, since, bot.id)
    if pair and pair[2] >= 3:
        a, b, n = pair
        hook = f"они сегодня {n} раз ответили друг другу и делают вид, что это случайно 👀"
    else:
        pool = [r["user_id"] for r in await db.daily_stats(chat_id, db.today()) if r["msgs"] >= 3]
        picked = games.pick_couple(pool)
        if not picked:
            return False
        a, b = picked
        hook = "не знаю почему, просто чувствую 👀"
    users = {u["user_id"]: u["name"] for u in await db.users_by_ids(chat_id, [a, b])}
    name_a, name_b = users.get(a, "кто-то"), users.get(b, "кто-то")
    poll_id = await db.create_poll(chat_id, a, b, name_a, name_b)
    sent = await say(bot, chat_id,
                     f"💘 <b>Чат, как вам пара?</b>\n\n{mention(a, name_a)} + {mention(b, name_b)}\n\n{hook}",
                     markup=poll_markup(poll_id, 0, 0))
    await db.set_poll_message(poll_id, sent.message_id)
    await talk.remember_self(bot, chat, sent, f"чат, как вам пара: {name_a} + {name_b}?")
    return True


async def on_pair_vote(cb: CallbackQuery) -> None:
    try:
        _, poll_id, vote = cb.data.split(":")
        poll_id, vote = int(poll_id), int(vote)
    except ValueError:
        return await cb.answer()
    poll = await db.get_poll(poll_id)
    if not poll or poll["closed"]:
        return await cb.answer("голосование уже закрыто")
    await db.vote_poll(poll_id, cb.from_user.id, vote)
    yes, no = await db.poll_counts(poll_id)
    try:
        await cb.message.edit_reply_markup(reply_markup=poll_markup(poll_id, yes, no))
    except Exception:
        pass
    await cb.answer("💘 голос учтён" if vote else "🙅 голос учтён")


async def close_polls(bot: Bot) -> None:
    for poll in await db.polls_to_close(time.time() - POLL_DURATION):
        await db.close_poll(poll["id"])
        yes, no = await db.poll_counts(poll["id"])
        a, b = mention(poll["user1"], poll["name1"]), mention(poll["user2"], poll["name2"])
        if yes + no == 0:
            verdict = "никто не проголосовал. чат, вам что, всё равно на любовь?"
        elif yes > no:
            verdict = random.choice([f"чат одобряет. {a}, {b}, готовьте свадьбу, я свидетель 💍",
                                     f"народ сказал своё слово: {a} и {b} теперь официально пара дня 💘"])
        elif no > yes:
            verdict = random.choice([f"чат не верит. {a} и {b}, расходимся, это была ошибка 💔",
                                     f"не судьба. {a}, {b}, остаёмся друзьями 🤝"])
        else:
            verdict = "ничья. чат в замешательстве, как и я"
        try:
            await bot.edit_message_reply_markup(chat_id=poll["chat_id"], message_id=poll["message_id"],
                                                reply_markup=None)
        except Exception:
            pass
        try:
            await say(bot, poll["chat_id"], f"🗳 <b>Голосование закрыто</b>\n💘 {yes} против 🙅 {no}\n\n{verdict}")
        except Exception as exc:
            log.warning("Итог пары не отправился в %s: %s", poll["chat_id"], exc)


# ---------- итоги дня ----------

async def post_results(bot: Bot, chat, manual: bool = False, reply_to=None) -> bool:
    """Итоги дня. manual: вызвали командой «итоги» посреди дня, тогда хватит и 5 сообщений."""
    chat_id, day = chat["chat_id"], db.today()
    since = midnight_ts()
    people = nominations.people_from_daily(await db.daily_stats(chat_id, day), await db.reacts_by_user(chat_id, since))
    nom = nominations.nominate(people, min_msgs=10)
    if nom.total < (MANUAL_MIN_MSGS if manual else RESULTS_MIN_MSGS):
        return False

    couple = await db.get_couple(chat_id, day)
    if couple is None:
        picked = games.pick_couple([p.user_id for p in people if p.msgs > 0])
        if picked:
            await db.set_couple(chat_id, day, *picked)
            couple = await db.get_couple(chat_id, day)
    top_msg = await db.top_reacted(chat_id, since)

    stats = "\n".join(f"{p.name}: {p.msgs} сообщ., мат {p.mat_pct}%" for p in
                      sorted(people, key=lambda p: -p.msgs)[:15])
    rows = await db.history_since(chat_id, since, limit=600)
    system, _ = await talk.context(chat)
    data = await ai.chat_json([{"role": "system", "content": system},
                               {"role": "user", "content": prompts.day_task(prompts.transcript(rows, 250, 120),
                                                                            stats)}], max_tokens=400)

    now = datetime.now(config.TZ)
    date = human_date(now.strftime("%m-%d"))
    title = f"📊 <b>Итоги дня на {now:%H:%M}</b>" if manual else "🌙 <b>Итоги дня</b>"
    lines = [title,
             f"{date} · {nom.total} {plural(nom.total, MSGS)} · {nom.people} чел.", ""]
    lines += [line.replace("<b>Болтун:</b>", "<b>Болтун дня:</b>") for line in nominees_html(nom)]
    if couple:
        users = {u["user_id"]: u["name"] for u in await db.users_by_ids(chat_id, [couple["user1"], couple["user2"]])}
        lines.insert(4, f"💞 <b>Пара дня:</b> {mention(couple['user1'], users.get(couple['user1'], 'кто-то'))} + "
                        f"{mention(couple['user2'], users.get(couple['user2'], 'кто-то'))}")
    rude = rude_line(data)
    if rude:
        lines.append(rude)
    if top_msg:
        lines += ["", f"🔥 <b>Сообщение дня</b> · {top_msg['total']} {plural(top_msg['total'], REACTS)}",
                  f"<blockquote>{mention(top_msg['user_id'], top_msg['name'])}\n{esc(top_msg['text'][:300])}</blockquote>"]
    word = prompts.clean_reply(str((data or {}).get("joke") or ""), chat["bot_name"]) or random.choice(DAY_WORDS)
    lines += ["", f"🕷 <b>{esc(chat['bot_name'])} о сегодняшнем дне</b>", esc(word)]
    sent = await say(bot, chat_id, "\n".join(lines), reply_to=reply_to)
    await talk.remember_self(bot, chat, sent, f"[итоги дня] {word}")
    return True


# ---------- дни рождения ----------

async def greet_birthdays(bot: Bot, chat) -> None:
    now = datetime.now(config.TZ)
    for user in await db.birthdays_today(chat["chat_id"], now.strftime("%m-%d"), now.year):
        await db.mark_bday(chat["chat_id"], user["user_id"], now.year)
        system, _ = await talk.context(chat)
        text = prompts.clean_reply(await ai.chat([{"role": "system", "content": system},
                                                  {"role": "user", "content": prompts.bday_task(user["name"],
                                                                                                 user["notes"])}],
                                                 max_tokens=250) or "", chat["bot_name"], limit=700)
        text = text or random.choice(BDAY_TEMPLATES).format(name=user["name"])
        await say(bot, chat["chat_id"],
                  f"🎂 <b>День рождения:</b> {mention(user['user_id'], user['name'])}!\n\n{esc(text)}")


# ---------- планировщик ----------

async def tick(bot: Bot) -> None:
    if license.sleeping():
        await license.tick(bot)
        return
    now = datetime.now(config.TZ)
    day = db.today()
    for chat in await db.list_chats():
        try:
            if chat["results"] and now.hour == chat["results_hour"] and chat["last_results"] != day:
                await db.update_chat(chat["chat_id"], last_results=day)
                await post_results(bot, chat)
            if (chat["pairpoll"] and chat["last_pairpoll"] != day and POLL_HOURS[0] <= now.hour < POLL_HOURS[1]
                    and random.random() < POLL_CHANCE
                    and await db.chat_message_count(chat["chat_id"], time.time() - 3600) >= POLL_ACTIVE_MSGS):
                await db.update_chat(chat["chat_id"], last_pairpoll=day)
                await start_pair_poll(bot, chat)
            if chat["bday"] and now.hour >= BDAY_HOUR:
                await greet_birthdays(bot, chat)
        except Exception:
            log.exception("Плановая задача в чате %s не выполнилась", chat["chat_id"])
    await close_polls(bot)
    await stars.expire_titles(bot)
    await stars.refresh_looks()
    await approval.tick(bot)
    await license.tick(bot)
    await license.remind_main(bot)


async def run_scheduler(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в ежедневном планировщике")
        await asyncio.sleep(CHECK_EVERY)
