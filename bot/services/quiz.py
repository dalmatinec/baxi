"""Викторина по теме чата. Вопросы придумывает нейросеть из темы, заданной в /admin,
и из недавней переписки. Кто первым нажал правильный вариант, получает очки."""

import asyncio
import logging
import random
import secrets
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import ai, db, prompts
from bot.services import talk
from bot.services.out import say, thread_of
from bot.textutil import esc, mention

log = logging.getLogger(__name__)

QUESTIONS = 5
POINTS = 10
ANSWER_TIME = 40   # секунд на вопрос
PAUSE = 5          # пауза между вопросами
LETTERS = "АБВГ"


@dataclass
class Question:
    q: str
    options: list[str]
    answer: int


@dataclass
class Game:
    chat_id: int
    token: str
    questions: list[Question]
    idx: int = 0
    solved: asyncio.Event = field(default_factory=asyncio.Event)
    wrong: set[int] = field(default_factory=set)
    winner: tuple[int, str] | None = None
    round_scores: dict[int, list] = field(default_factory=dict)  # user_id → [имя, очки]


_games: dict[int, Game] = {}
_tasks: set[asyncio.Task] = set()


def parse_questions(data: dict | None, limit: int = QUESTIONS) -> list[Question]:
    """Проверяем, что модель вернула нормальные вопросы: текст, 4 варианта, номер правильного."""
    out = []
    for item in (data or {}).get("questions", []) if isinstance(data, dict) else []:
        try:
            q = str(item["q"]).strip()
            options = [str(o).strip()[:40] for o in item["options"]]
            answer = int(item["answer"])
        except (KeyError, TypeError, ValueError):
            continue
        if q and len(options) == 4 and all(options) and len(set(options)) == 4 and 0 <= answer < 4:
            out.append(Question(q[:300], options, answer))
    return out[:limit]


def running(chat_id: int) -> bool:
    return chat_id in _games


async def start(bot: Bot, chat, message: Message) -> None:
    chat_id = chat["chat_id"]
    if chat_id in _games:
        await say(bot, chat_id, "викторина уже идёт, отвечай на текущий вопрос", reply_to=message)
        return
    _games[chat_id] = Game(chat_id, "", [])  # занимаем чат, пока готовим вопросы
    count = chat["quiz_count"] if chat["quiz_count"] in (5, 10) else QUESTIONS
    try:
        await talk.typing(bot, chat_id, "...")
        rows = await db.recent_history(chat_id, 80)
        system, _ = await talk.context(chat)
        data = await ai.chat_json([{"role": "system", "content": system},
                                   {"role": "user", "content": prompts.quiz_task(chat["topic"],
                                                                                  prompts.transcript(rows, 80, 120),
                                                                                  count)}],
                                  max_tokens=250 * count + 200, temperature=0.8)
        questions = parse_questions(data, count)
    except Exception:
        log.exception("Викторина не собралась")
        questions = []
    if len(questions) < 3:
        _games.pop(chat_id, None)
        await say(bot, chat_id, "не получилось придумать вопросы, давай попозже", reply_to=message)
        return
    game = Game(chat_id, secrets.token_hex(3), questions)
    _games[chat_id] = game
    task = asyncio.create_task(_run(bot, game, thread_of(message)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _keyboard(game: Game) -> InlineKeyboardMarkup:
    q = game.questions[game.idx]
    buttons = [InlineKeyboardButton(text=f"{LETTERS[i]}. {opt}", callback_data=f"qz:{game.token}:{game.idx}:{i}")
               for i, opt in enumerate(q.options)]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])


async def _run(bot: Bot, game: Game, thread: int | None) -> None:
    chat_id = game.chat_id
    total = len(game.questions)
    try:
        await say(bot, chat_id, f"🧠 <b>Викторина!</b> {total} вопросов, кто первый ответит правильно, "
                                f"получает +{POINTS}. на каждый вопрос {ANSWER_TIME} секунд", thread=thread)
        for i, q in enumerate(game.questions):
            game.idx, game.wrong, game.winner = i, set(), None
            game.solved = asyncio.Event()
            await asyncio.sleep(PAUSE)
            sent = await say(bot, chat_id, f"🧠 <b>Вопрос {i + 1} из {total}</b>\n\n{esc(q.q)}",
                             thread=thread, markup=_keyboard(game))
            try:
                await asyncio.wait_for(game.solved.wait(), ANSWER_TIME)
            except asyncio.TimeoutError:
                pass
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=sent.message_id, reply_markup=None)
            except Exception:
                pass
            right = f"{LETTERS[q.answer]}. {esc(q.options[q.answer])}"
            if game.winner:
                uid, name = game.winner
                await say(bot, chat_id, f"✅ правильно: <b>{right}</b>\nпервым ответил {mention(uid, name)}, "
                                        f"+{POINTS}", reply_to=sent)
            else:
                await say(bot, chat_id, f"⏰ никто не угадал. правильно: <b>{right}</b>", reply_to=sent)
        await _finish(bot, game, thread)
    except Exception:
        log.exception("Викторина в чате %s сломалась", chat_id)
    finally:
        _games.pop(chat_id, None)


async def _finish(bot: Bot, game: Game, thread: int | None) -> None:
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏁 <b>Викторина окончена</b>", ""]
    ranking = sorted(game.round_scores.items(), key=lambda kv: -kv[1][1])
    if ranking:
        for n, (uid, (name, pts)) in enumerate(ranking[:5]):
            lines.append(f"{medals[n] if n < 3 else f'{n + 1}.'} {mention(uid, name)}: {pts}")
    else:
        lines.append("в этот раз никто ничего не угадал, позор чату")
    top = await db.quiz_top(game.chat_id, 3)
    if top:
        lines += ["", "<b>Общий топ знатоков:</b> " + ", ".join(f"{mention(r['user_id'], r['name'])} {r['points']}" for r in top)]
    await say(bot, game.chat_id, "\n".join(lines), thread=thread)


async def on_answer(cb: CallbackQuery) -> None:
    try:
        _, token, idx, choice = cb.data.split(":")
        idx, choice = int(idx), int(choice)
    except ValueError:
        return await cb.answer()
    game = _games.get(cb.message.chat.id) if cb.message else None
    if not game or game.token != token or game.idx != idx or game.solved.is_set():
        return await cb.answer("этот вопрос уже закрыт")
    user = cb.from_user
    if user.id in game.wrong:
        return await cb.answer("ты уже отвечал на этот вопрос")
    if choice != game.questions[idx].answer:
        game.wrong.add(user.id)
        return await cb.answer(random.choice(["❌ мимо", "❌ не-а", "❌ промах"]))
    name = " ".join(x for x in (user.first_name, user.last_name) if x) or "аноним"
    game.winner = (user.id, name)
    game.solved.set()
    game.round_scores.setdefault(user.id, [name, 0])[1] += POINTS
    await db.quiz_add(game.chat_id, user.id, POINTS)
    await cb.answer(f"✅ верно! +{POINTS}")
