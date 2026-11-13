"""Как бот говорит: собирает контекст чата, спрашивает нейросеть или берёт фразу из базы,
«печатает» и отправляет. Всё, что бот написал, тоже попадает в историю чата."""

import asyncio
import logging
import random

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.types import Message

from bot import ai, brain, config, db, prompts
from bot.services.out import reply_params as _reply
from bot.services.out import say, thread_of  # noqa: F401  (thread_of нужен другим модулям)
from bot.textutil import esc, humanize, mention

log = logging.getLogger(__name__)

_locks: dict[int, asyncio.Lock] = {}

GREETINGS = [
    "о, {name} подъехал, заходи не стесняйся",
    "{name}, привет! ты к нам надолго?",
    "смотрите кто пришёл, {name}! рассказывай, кто такой",
    "{name}, здарова. тут все свои, почти",
    "опа, новенький. {name}, чай, кофе, мемы?",
    "{name}, добро пожаловать в дурку, тапочки выдаём на входе",
    "{name}, привет-привет! правила простые: не душнить",
]

FALLBACK_REPLIES = ["щас не до тебя, позже", "ага", "ну допустим", "отстань, я думаю", "хм"]


def chat_lock(chat_id: int) -> asyncio.Lock:
    return _locks.setdefault(chat_id, asyncio.Lock())


async def context(chat) -> tuple[str, str]:
    """Системный промпт с заметками об участниках и текст последних сообщений."""
    rows = await db.recent_history(chat["chat_id"], config.CONTEXT_MESSAGES)
    ids = list(dict.fromkeys(r["user_id"] for r in rows if not r["is_bot"]))[-8:]
    users = await db.users_by_ids(chat["chat_id"], ids)
    notes = [f"{u['name']}: {u['notes']}" for u in users if u["notes"]]
    system = prompts.system_prompt(chat["bot_name"], chat["persona"], chat["topic"],
                                   chat["title"] or "без названия", notes)
    return system, prompts.format_history(rows, chat["bot_name"])


async def _ask(chat, make_task) -> str | None:
    """make_task получает историю чата текстом и возвращает задание для нейросети."""
    system, history = await context(chat)
    answer = await ai.chat([{"role": "system", "content": system},
                            {"role": "user", "content": make_task(history)}])
    text = prompts.clean_reply(answer or "", chat["bot_name"])
    return text or None


async def typing(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
    except Exception:
        pass
    await asyncio.sleep(brain.typing_delay(text))


async def remember_self(bot: Bot, chat, sent: Message, text: str, reply_name: str = "") -> None:
    await db.add_history(chat["chat_id"], sent.message_id, bot.id, chat["bot_name"], humanize(text),
                         reply_name=reply_name, is_bot=True)


async def send_text(bot: Bot, chat, text_html: str, plain: str, reply_to: Message | None = None,
                    reply_name: str = "", thread: int | None = None) -> None:
    await typing(bot, chat["chat_id"], plain)
    sent = await say(bot, chat["chat_id"], text_html, reply_to=reply_to, thread=thread)
    await remember_self(bot, chat, sent, plain, reply_name)


async def ai_answer(bot: Bot, chat, message: Message, author: str, text: str, jump: bool) -> None:
    """Ответ нейросети на сообщение. Не вышло (лимит, ошибка), отвечает фразой из базы."""
    build = prompts.jump_task if jump else prompts.reply_task
    reply = await _ask(chat, lambda history: build(history, author, text or "[без текста]"))
    if reply is None:
        if jump:
            return await phrase_answer(bot, chat, message, author)
        reply = await db.random_phrase("text") or random.choice(FALLBACK_REPLIES)
    await send_text(bot, chat, esc(reply), reply, reply_to=message, reply_name=author)


async def phrase_answer(bot: Bot, chat, message: Message, author: str) -> None:
    """Случайная реплика из базы: текст в ответ или с тегом кого-то из чата, стикер, гифка."""
    chat_id = chat["chat_id"]
    kind = brain.pick_phrase_kind()
    if kind in ("sticker", "gif"):
        file_id = await db.random_phrase(kind)
        if file_id:
            await asyncio.sleep(random.uniform(1, 3))
            try:
                if kind == "sticker":
                    sent = await bot.send_sticker(chat_id, file_id, reply_parameters=_reply(message))
                else:
                    sent = await bot.send_animation(chat_id, file_id, reply_parameters=_reply(message))
                await remember_self(bot, chat, sent, "[стикер]" if kind == "sticker" else "[гифка]", author)
                return
            except Exception as exc:
                log.warning("Не отправился %s %s: %s", kind, file_id[:20], exc)
    phrase = await db.random_phrase("text")
    if not phrase:
        return
    if random.random() < 0.5:
        await send_text(bot, chat, esc(phrase), phrase, reply_to=message, reply_name=author)
        return
    # тегнуть кого-нибудь из недавно писавших, как живой участник
    people = [u for u in await db.active_users(chat_id, days=1, limit=30) if u["user_id"] != bot.id]
    if not people:
        await send_text(bot, chat, esc(phrase), phrase, reply_to=message, reply_name=author)
        return
    who = random.choice(people)
    await send_text(bot, chat, f"{mention(who['user_id'], who['name'])}, {esc(phrase)}",
                    f"{who['name']}, {phrase}", thread=thread_of(message))


async def greet(bot: Bot, chat, user_id: int, name: str, thread: int | None = None) -> None:
    text = await _ask(chat, lambda history: prompts.greet_task(name, history))
    if text and name.lower() in text.lower():
        # имя в тексте делаем кликабельным, чтобы новичку пришло уведомление
        i = text.lower().index(name.lower())
        html_text = esc(text[:i]) + mention(user_id, text[i:i + len(name)]) + esc(text[i + len(name):])
    elif text:
        html_text = f"{mention(user_id, name)}, {esc(text)}"
        text = f"{name}, {text}"
    else:
        text = random.choice(GREETINGS).format(name=name)
        html_text = esc(text).replace(esc(name), mention(user_id, name), 1)
    await send_text(bot, chat, html_text, text, thread=thread)
