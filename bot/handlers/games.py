"""Игры в чате: пара дня, шип, кто, предсказание."""

import random
import time
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from bot import brain, config, db, games
from bot.services import quiz, stars
from bot.middlewares import GROUPS
from bot.services.out import say
from bot.textutil import full_name, human_date, humanize, mention

router = Router(name="games")

HELP_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎯 Викторина", callback_data="gm:quiz"),
     InlineKeyboardButton(text="💘 Пара дня", callback_data="gm:couple")],
    [InlineKeyboardButton(text="📊 Итоги", callback_data="gm:results"),
     InlineKeyboardButton(text="🏆 Топ репы", callback_data="gm:rep_top")],
    [InlineKeyboardButton(text="🔮 Предсказание", callback_data="gm:predict"),
     InlineKeyboardButton(text="🔥 Прожарка ⭐", callback_data="gm:roast")],
] + ([[InlineKeyboardButton(text="📖 Все команды на сайте", url=f"{config.SITE_URL}/baxi#commands")]]
     if config.SITE_URL else []))


async def couple_html(bot: Bot, chat_id: int) -> str:
    day = db.today()
    couple = await db.get_couple(chat_id, day)
    if couple is None:
        ids = [u["user_id"] for u in await db.active_users(chat_id, days=7) if u["user_id"] != bot.id]
        picked = games.pick_couple(ids)
        if picked is None:
            return "мало народу для пары, пусть сначала кто-нибудь ещё напишет"
        await db.set_couple(chat_id, day, *picked)
        couple = await db.get_couple(chat_id, day)
    users = {u["user_id"]: u for u in await db.users_by_ids(chat_id, [couple["user1"], couple["user2"]])}
    a, b = users.get(couple["user1"]), users.get(couple["user2"])
    tpl = random.Random(f"{chat_id}:{day}").choice(games.COUPLE_TEMPLATES)
    return tpl.format(a=mention(couple["user1"], a["name"] if a else "кто-то"),
                      b=mention(couple["user2"], b["name"] if b else "кто-то"))


async def top_html(chat_id: int, name: str) -> str:
    rows = await (db.rep_top if name == "rep_top" else db.quiz_top)(chat_id, 10)
    title = "🏆 <b>Топ репутации</b>" if name == "rep_top" else "🧠 <b>Топ знатоков викторины</b>"
    if not rows:
        return title + "\n\nпока пусто"
    medals = ["🥇", "🥈", "🥉"]
    names = await stars.decorate(rows)
    lines = [f"{medals[i] if i < 3 else f'{i + 1}.'} {mention(r['user_id'], names[r['user_id']])}: "
             f"<b>{r['points']}</b>" for i, r in enumerate(rows)]
    return title + "\n\n" + "\n".join(lines)


def predict_html(user: User) -> str:
    rnd = random.Random(f"{user.id}:{db.today()}")
    return f"🔮 {mention(user.id, full_name(user.first_name, user.last_name))}, {rnd.choice(games.PREDICTIONS)}"


async def game_filter(message: Message, chat_row=None) -> dict | bool:
    """Срабатывает, только если в чате включены игры и текст похож на команду игры."""
    if chat_row is None or not chat_row["games"]:
        return False
    found = games.match(message.text or "")
    if not found:
        return False
    # «кто ты, марат?» или ответ на чьё-то сообщение — это вопрос, а не игра
    if found[0] == "who" and (message.reply_to_message is not None or brain.mentions_name(
            message.text, brain.parse_aliases(chat_row["bot_name"], chat_row["aliases"]))):
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
        return await say(bot, chat_id, games.HELP, reply_to=message, markup=HELP_KB)

    if name == "predict":
        return await _send(message, predict_html(message.from_user))

    if name == "couple":
        return await _send(message, await couple_html(bot, chat_id))

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
        if not chat_row["quiz"]:
            return await _send(message, "викторины в этом чате выключены")
        return await quiz.start(bot, chat_row, message)

    if name in ("rep_top", "quiz_top"):
        return await _send(message, await top_html(chat_id, name))

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
        # создателя в «кто самый ...» не выбираем: вопросы там бывают обидные
        people = [u for u in await db.active_users(chat_id, days=3, limit=100)
                  if u["user_id"] != me.id and u["user_id"] not in config.CREATOR_IDS]
        if not people:
            return await _send(message, "тут пока никого, кроме меня")
        who = random.choice(people)
        return await _send(message, random.choice(games.WHO_TEMPLATES).format(
            who=mention(who["user_id"], who["name"])))


@router.callback_query(F.data.startswith("gm:"))
async def on_game_button(cb: CallbackQuery, bot: Bot) -> None:
    """Кнопки под /games в чате."""
    if not cb.message or cb.message.chat.type not in GROUPS:
        return await cb.answer()
    chat = await db.get_chat(cb.message.chat.id)
    if not chat or not chat["approved"] or not chat["games"]:
        return await cb.answer("игры в этом чате выключены", show_alert=True)
    action, chat_id = cb.data[3:], chat["chat_id"]
    if action == "roast":
        return await cb.answer("Ответь словом магазин на сообщение человека или напиши мне: "
                               "прожарь его по полной", show_alert=True)
    if action == "quiz":
        if not chat["quiz"]:
            return await cb.answer("викторины в этом чате выключены", show_alert=True)
        await cb.answer("🧠 готовлю вопросы...")
        return await quiz.start(bot, chat, cb.message)
    if action == "results":
        from bot.services import daily, perms
        wait = daily.MANUAL_RESULTS_EVERY - (time.time() - chat["results_manual"])
        admin = await perms.is_admin_id(bot, chat_id, cb.from_user.id)
        if wait > 0 and not admin and not await stars.is_vip(cb.from_user.id):
            return await cb.answer(f"итоги уже были, следующие через {max(1, round(wait / 60))} мин", show_alert=True)
        await cb.answer()
        await db.update_chat(chat_id, results_manual=time.time())
        if not await daily.post_results(bot, chat, manual=True):
            await db.update_chat(chat_id, results_manual=chat["results_manual"])
            await say(bot, chat_id, "сегодня тут почти тихо, итожить нечего")
        return
    await cb.answer()
    if action == "couple":
        html = await couple_html(bot, chat_id)
    elif action == "rep_top":
        html = await top_html(chat_id, "rep_top")
    elif action == "predict":
        html = predict_html(cb.from_user)
    else:
        return
    await say(bot, chat_id, html)
