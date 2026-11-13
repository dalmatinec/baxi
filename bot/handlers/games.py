"""Игры в чате: пара дня, шип, кто, предсказание."""

import random
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.types import Message

from bot import brain, config, db, games
from bot.services import quiz, stars
from bot.middlewares import GROUPS
from bot.textutil import full_name, human_date, humanize, mention

router = Router(name="games")


async def game_filter(message: Message, chat_row=None) -> dict | bool:
    """Срабатывает, только если в чате включены игры и текст похож на команду игры."""
    if chat_row is None or not chat_row["games"]:
        return False
    found = games.match(message.text or "")
    if not found:
        return False
    # «кто ты, марат?» — это вопрос боту, а не игра
    if found[0] == "who" and brain.mentions_name(message.text, brain.parse_aliases(chat_row["bot_name"],
                                                                                    chat_row["aliases"])):
        return False
    return {"game": found}


async def _send(message: Message, html: str) -> None:
    await message.reply(humanize(html), parse_mode="HTML")


@router.message(F.chat.type.in_(GROUPS), F.text, game_filter)
async def on_game(message: Message, bot: Bot, game: tuple[str, str], chat_row) -> None:
    name, tail = game
    chat_id = message.chat.id
    day = db.today()
    me = await bot.me()

    if name == "help":
        return await _send(message, games.HELP)

    if name == "predict":
        rnd = random.Random(f"{message.from_user.id}:{day}")
        return await _send(message, f"🔮 {rnd.choice(games.PREDICTIONS)}")

    if name == "couple":
        couple = await db.get_couple(chat_id, day)
        if couple is None:
            ids = [u["user_id"] for u in await db.active_users(chat_id, days=7) if u["user_id"] != me.id]
            picked = games.pick_couple(ids)
            if picked is None:
                return await _send(message, "мало народу для пары, пусть сначала кто-нибудь ещё напишет")
            await db.set_couple(chat_id, day, *picked)
            couple = await db.get_couple(chat_id, day)
        users = {u["user_id"]: u for u in await db.users_by_ids(chat_id, [couple["user1"], couple["user2"]])}
        a = users.get(couple["user1"])
        b = users.get(couple["user2"])
        a_html = mention(couple["user1"], a["name"] if a else "кто-то")
        b_html = mention(couple["user2"], b["name"] if b else "кто-то")
        tpl = random.Random(f"{chat_id}:{day}").choice(games.COUPLE_TEMPLATES)
        return await _send(message, tpl.format(a=a_html, b=b_html))

    if name == "ship":
        rt = message.reply_to_message
        if not rt or not rt.from_user or rt.from_user.is_bot or rt.from_user.id == message.from_user.id:
            return await _send(message, "напиши шип в ответ на сообщение того, с кем проверить совместимость")
        a, b = message.from_user, rt.from_user
        p = games.ship_percent(a.id, b.id, day)
        return await _send(message,
                           f"💞 {mention(a.id, full_name(a.first_name, a.last_name))} + "
                           f"{mention(b.id, full_name(b.first_name, b.last_name))}\n"
                           f"{games.ship_bar(p)} <b>{p}%</b>\n{games.ship_comment(p)}")

    if name == "quiz":
        return await quiz.start(bot, chat_row, message)

    if name in ("rep_top", "quiz_top"):
        rows = await (db.rep_top if name == "rep_top" else db.quiz_top)(chat_id, 10)
        title = "🏆 <b>Топ репутации</b>" if name == "rep_top" else "🧠 <b>Топ знатоков викторины</b>"
        if not rows:
            return await _send(message, title + "\n\nпока пусто")
        medals = ["🥇", "🥈", "🥉"]
        names = await stars.decorate(rows)
        lines = [f"{medals[i] if i < 3 else f'{i + 1}.'} {mention(r['user_id'], names[r['user_id']])}: "
                 f"<b>{r['points']}</b>" for i, r in enumerate(rows)]
        return await _send(message, title + "\n\n" + "\n".join(lines))

    if name == "donors_top":
        from bot.handlers.stars import donors_text
        return await _send(message, await donors_text(await db.chat_user_ids(chat_id)))

    if name == "rep_me":
        rt = message.reply_to_message
        who = rt.from_user if rt and rt.from_user and not rt.from_user.is_bot else message.from_user
        points = await db.rep_get(chat_id, who.id)
        return await _send(message, f"⭐ репутация {mention(who.id, full_name(who.first_name, who.last_name))}: "
                                    f"<b>{points}</b>")

    if name == "bdays":
        rows = await db.all_birthdays(chat_id)
        if not rows:
            return await _send(message, "🎂 никто ещё не сказал свой др. напиши: мой др 12.05")
        today_mmdd = datetime.now(config.TZ).strftime("%m-%d")
        rows = sorted(rows, key=lambda r: (r["birthday"] < today_mmdd, r["birthday"]))[:10]
        return await _send(message, "🎂 <b>Ближайшие дни рождения</b>\n\n" + "\n".join(
            f"{human_date(r['birthday'])}: {mention(r['user_id'], r['name'])}" for r in rows))

    if name == "who":
        people = [u for u in await db.active_users(chat_id, days=3, limit=100) if u["user_id"] != me.id]
        if not people:
            return await _send(message, "тут пока никого, кроме меня")
        who = random.choice(people)
        return await _send(message, random.choice(games.WHO_TEMPLATES).format(
            who=mention(who["user_id"], who["name"])))
