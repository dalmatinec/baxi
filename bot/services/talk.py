"""Как бот говорит: собирает контекст чата, спрашивает нейросеть или берёт фразу из базы,
«печатает» и отправляет. Всё, что бот написал, тоже попадает в историю чата."""

import asyncio
import logging
import random
import re
import time

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.types import Message

from bot import ai, brain, config, db, prompts, slang
from bot.services.out import reply_params as _reply
from bot.services.out import say, thread_of  # noqa: F401  (thread_of нужен другим модулям)
from bot.textutil import esc, humanize, is_laugh, is_mat, mention

log = logging.getLogger(__name__)

_locks: dict[int, asyncio.Lock] = {}

GREETINGS = [
    "{name} подъехал, заходи не стесняйся",
    "{name}, привет! ты к нам надолго?",
    "смотрите кто пришёл, {name}! рассказывай, кто такой",
    "{name}, здарова. тут все свои, почти",
    "опа, новенький. {name}, чай, кофе, мемы?",
    "{name}, добро пожаловать в дурку, тапочки выдаём на входе",
    "{name}, привет-привет! правила простые: не душнить",
]



def chat_lock(chat_id: int) -> asyncio.Lock:
    return _locks.setdefault(chat_id, asyncio.Lock())


async def rules(chat) -> list[str]:
    """Правила чата для нейросети: юмор, мат, запретные темы, эмодзи, создатель."""
    from bot import presets
    from bot.services import emoji
    out = [presets.HUMOR_RULE.get(chat["humor"], ""), presets.MAT_RULE.get(chat["mat"], "")]
    if chat["banned"]:
        out.append(f"Никогда не шути и не говори на эти темы, уходи от них: {chat['banned']}.")
    out.append(prompts.emoji_rule(emoji.alts()))
    out.append(prompts.features_block(bool(chat["shop"])))   # бот знает свои команды и правила монет
    if config.CREATOR_IDS:
        contact = config.CREATOR_CONTACT
        if not contact:
            for uid in sorted(config.CREATOR_IDS):
                username = await db.username_of(uid)
                if username:
                    contact = "@" + username
                    break
        out.append(prompts.creator_block(config.CREATOR_NAME, contact))
    return [x for x in out if x]


_style_cache: dict[int, tuple[float, str, float]] = {}


async def chat_style(chat_id: int) -> str:
    """Как пишут в чате, по 200 последним сообщениям людей. Пересчитывается раз в час."""
    hit = _style_cache.get(chat_id)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    rows = await db.recent_history(chat_id, 200)
    texts = [r["text"] for r in rows if not r["is_bot"] and r["text"]]
    hint = prompts.chat_style(texts)
    commas = sum(t.count(",") for t in texts) / len(texts) if texts else 0.0
    _style_cache[chat_id] = (time.time(), hint, commas)
    return hint


def few_commas(chat_id: int) -> bool:
    """В чате почти не ставят запятые (меньше одной на сообщение): бот тоже пишет без них."""
    hit = _style_cache.get(chat_id)
    return hit is None or hit[2] < 1.0


_people_cache: dict[int, tuple[float, list]] = {}


async def about_people(chat, texts: list[str], skip: set[int]) -> list[str]:
    """Люди, которых назвали по имени в разговоре, но которые сами сейчас не пишут: заметка или «участник чата».
    Список людей кешируется на 10 минут, поиск по именам идёт в памяти, без нейросети."""
    hit = _people_cache.get(chat["chat_id"])
    if not hit or time.time() - hit[0] > 600:
        rows = await db.people_index(chat["chat_id"])
        # свой чат первым, потом самые активные: при одинаковых именах берём их
        rows.sort(key=lambda r: (r["chat_id"] != chat["chat_id"], -r["msg_count"]))
        hit = (time.time(), [(prompts.name_key(r["name"]), dict(r)) for r in rows])
        _people_cache[chat["chat_id"]] = hit
    bot_key = prompts.name_key(chat["bot_name"])
    people = [(k, p) for k, p in hit[1] if k != bot_key and p["user_id"] not in skip]
    out = []
    for p in prompts.mentioned(texts, people)[:4]:
        if p["notes"] and (p["chat_id"] == chat["chat_id"] or chat["share_notes"]):
            out.append(f"{p['name']}: {p['notes']}")
        elif p["chat_id"] == chat["chat_id"]:
            out.append(f"{p['name']}: участник этого чата, заметок пока нет")
    return out


async def context(chat) -> tuple[str, str]:
    """Системный промпт с заметками об участниках и текст последних сообщений."""
    rows = await db.recent_history(chat["chat_id"], config.CONTEXT_MESSAGES)
    ids = list(dict.fromkeys(r["user_id"] for r in rows if not r["is_bot"]))[-12:]
    users = await db.users_by_ids(chat["chat_id"], ids)
    vips = await db.vip_ids(ids)
    notes = [f"{u['name']}: {u['notes']}" for u in users if u["notes"]]
    notes += [f"{u['name']}: VIP чата, обращайся к нему с шутливым уважением" for u in users if u["user_id"] in vips]
    shared = []
    if chat["share_notes"]:   # общая память: кого здесь ещё не знаем, узнаём по заметкам из других чатов
        known = {u["user_id"] for u in users if u["notes"]}
        names = {u["user_id"]: u["name"] for u in users}
        other = await db.notes_elsewhere(chat["chat_id"], [i for i in ids if i not in known and i in names])
        shared = [f"{names[i]}: {n}" for i, n in other.items()]
    talk_texts = [r["text"] for r in rows if not r["is_bot"]][-8:]
    about = await about_people(chat, talk_texts, set(ids))
    from bot.services import plans
    system = prompts.system_prompt(chat["bot_name"], plans.persona(chat), chat["topic"],
                                   chat["title"] or "без названия", notes,
                                   (await rules(chat)) + [await chat_style(chat["chat_id"]),
                                                          slang.hint([r["text"] for r in rows if not r["is_bot"]][-8:])],
                                   shared, about)
    return system, prompts.format_history(rows, chat["bot_name"], config.CREATOR_IDS)


# ответы, которые только что придуманы, но ещё могут быть не записаны в историю: два одинаковых сообщения
# подряд обрабатываются параллельно и иначе не видят друг друга
_fresh: dict[int, list[tuple[float, str]]] = {}


def _fresh_texts(chat_id: int) -> list[str]:
    now = time.time()
    items = [(ts, t) for ts, t in _fresh.get(chat_id, []) if now - ts < 120]
    _fresh[chat_id] = items
    return [t for _, t in items]


SKIP = ""   # _ask вернул пустую строку: ответ повторяется даже со второй попытки, лучше промолчать


async def _ask(chat, make_task, incoming: str | None = None) -> str | None:
    """make_task получает историю чата текстом и возвращает задание для нейросети.
    incoming задан (ответ человеку или влезание в разговор): включаются фильтры. Срезаем «салам бро», если не
    здоровались; лишнее имя; хвост после третьей запятой. Повтор своих прошлых ответов или эхо сленга собеседника:
    одна перегенерация с подсказкой; если снова повтор, возвращаем SKIP (бот молчит). None: нейросеть не ответила."""
    system, history = await context(chat)
    task = prompts.now_line() + "\n" + make_task(history)
    if incoming is None:
        answer = await ai.chat([{"role": "system", "content": system}, {"role": "user", "content": task}])
        return prompts.clean_reply(answer or "", chat["bot_name"]) or None
    recent = await db.bot_replies(chat["chat_id"], 10)
    said = [t for t, _ in recent]
    names = await db.recent_names(chat["chat_id"])
    greeting = prompts.is_greeting(incoming)   # на «салам брат» здороваемся в ответ, повторы тут не считаются
    banned = set() if greeting else prompts.cooldown_words(recent, time.time())
    if banned:
        task += f"\nНе используй слова: {', '.join(sorted(banned))}."
    text = ""
    for attempt in range(2):
        answer = await ai.chat([{"role": "system", "content": system}, {"role": "user", "content": task}],
                               penalties=True)
        if not answer and ai.LAST_FAIL == "net":   # сбой связи: ещё одна попытка через пару секунд
            await asyncio.sleep(2.5)
            answer = await ai.chat([{"role": "system", "content": system}, {"role": "user", "content": task}],
                                   penalties=True)
        if not answer:
            return None
        text = prompts.clean_reply(answer, chat["bot_name"])
        text = prompts.strip_names(prompts.drop_hello(text, incoming), names, said)
        if few_commas(chat["chat_id"]):
            text = prompts.drop_commas(text)
        repeat = not greeting and prompts.is_repeat(text, said + _fresh_texts(chat["chat_id"]))
        echo = prompts.echo_words(incoming, text)
        if not text or not (repeat or echo):
            break
        if attempt == 1:
            if repeat:
                log.info("Чат %s: ответ повторяется, молчу: %s", chat["chat_id"], text[:80])
                return SKIP
            break
        hint = []
        if repeat:
            hint.append("Ты уже говорил почти так же: ответь на то же сообщение по смыслу, но другими словами.")
        if echo:
            hint.append(f"Не повторяй словечки собеседника ({', '.join(sorted(echo))}), отвечай на смысл.")
        task += "\n" + " ".join(hint)
    if text:
        _fresh.setdefault(chat["chat_id"], []).append((time.time(), text))
    return text or None


async def typing(bot: Bot, chat_id: int, text: str, since: float | None = None) -> None:
    """Пауза как у человека: «прочитал» и «печатает…». since: когда пришло сообщение, на которое отвечаем;
    время, пока думала нейросеть, уже прошло и вычитается. Значок «печатает» держится 5 секунд, обновляем."""
    left = brain.typing_delay(text) - (time.time() - since if since else 0)
    while left > 0:
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        step = min(left, 4.5)
        await asyncio.sleep(step)
        left -= step


async def remember_self(bot: Bot, chat, sent: Message, text: str, reply_name: str = "") -> None:
    await db.add_history(chat["chat_id"], sent.message_id, bot.id, chat["bot_name"], humanize(text),
                         reply_name=reply_name, is_bot=True)


async def send_text(bot: Bot, chat, text_html: str, plain: str, reply_to: Message | None = None,
                    reply_name: str = "", thread: int | None = None, since: float | None = None) -> None:
    """since: когда бот получил сообщение (часы сервера). Время Telegram в сообщении не берём: если часы сервера
    убежали вперёд, пауза пропадала совсем."""
    await typing(bot, chat["chat_id"], plain, since)
    sent = await say(bot, chat["chat_id"], text_html, reply_to=reply_to, thread=thread)
    await remember_self(bot, chat, sent, plain, reply_name)


async def ai_answer(bot: Bot, chat, message: Message, author: str, text: str, jump: bool) -> None:
    """Ответ нейросети на сообщение. Не вышло (лимит, ошибка), отвечает фразой из базы."""
    got = time.time()   # пауза «читает, печатает» считается от этого момента
    rt = message.reply_to_message
    me_id = (await bot.me()).id if rt else 0
    quoted = (rt.text or rt.caption or "") if rt and rt.from_user and rt.from_user.id == me_id else ""
    if jump:
        make = lambda history: prompts.jump_task(history, author, text or "[без текста]")  # noqa: E731
    else:
        make = lambda history: prompts.reply_task(history, author, text or "[без текста]", quoted)  # noqa: E731
    reply = await _ask(chat, make, incoming=text or "")
    creator = bool(message.from_user and message.from_user.id in config.CREATOR_IDS)
    if reply == SKIP:
        from bot.services import reactions
        await reactions.react(bot, chat, message)   # повторялся бы: вместо ответа реакция или молчим
        return
    if reply is None:
        if ai.LAST_FAIL == "net":
            # нейросеть не ответила даже со второй попытки: молчим, а не пишем «дай минутку»; владельцу сообщим
            await _warn_owner_net(bot)
            return
        if jump and not creator:
            return await phrase_answer(bot, chat, message, author)
        if not jump and not creator:
            # к боту обратились, а нейросеть сейчас нельзя (лимит, тариф): реакция вместо пустой заготовки
            from bot.services import reactions
            await reactions.react(bot, chat, message)
        return
    await send_text(bot, chat, esc(reply), reply, reply_to=message, reply_name=author, since=got)


_net_warned = 0.0


async def _warn_owner_net(bot: Bot) -> None:
    """Связи с нейросетью нет дольше 10 минут: раз в 2 часа пишем владельцу в личку, чтобы знал, в чём дело."""
    global _net_warned
    down = ai.net_down_minutes()
    if down < 10 or time.time() - _net_warned < 7200:
        return
    _net_warned = time.time()
    for uid in config.OWNER_IDS:
        try:
            await bot.send_message(uid, f"⚠️ Нет связи с нейросетью уже {int(down)} мин. Бот пока молчит на обращения, "
                                        "игры и команды работают. Обычно это сеть сервера или сбой у сервиса: "
                                        "проверь интернет на сервере и баланс DeepSeek.")
        except Exception:
            pass


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
    # по ситуации: смеются, матерятся или обычный разговор
    text = message.text or message.caption or ""
    cat = "laugh" if is_laugh(text) else "mat" if is_mat(text) else "text"
    phrase = await db.random_phrase(cat) or await db.random_phrase("text")
    if not phrase:
        return
    if cat != "text" or random.random() < 0.5:
        await send_text(bot, chat, esc(phrase), phrase, reply_to=message, reply_name=author)
        return
    # тегнуть кого-нибудь из недавно писавших, как живой участник
    people = [u for u in await db.active_users(chat_id, days=1, limit=30)
              if u["user_id"] != bot.id and u["user_id"] not in config.CREATOR_IDS]
    if not people:
        await send_text(bot, chat, esc(phrase), phrase, reply_to=message, reply_name=author)
        return
    who = random.choice(people)
    tagged = await db.random_phrase("tag")
    if tagged and "{name}" in tagged:
        html_text = esc(tagged).replace("{name}", mention(who["user_id"], who["name"]), 1)
        return await send_text(bot, chat, html_text, tagged.replace("{name}", who["name"]), thread=thread_of(message))
    await send_text(bot, chat, f"{mention(who['user_id'], who['name'])}, {esc(phrase)}",
                    f"{who['name']}, {phrase}", thread=thread_of(message))


_greeted: dict[int, list[str]] = {}   # последние приветствия в чате, чтобы не повторяться


def _remember_greet(chat_id: int, text: str) -> None:
    items = _greeted.setdefault(chat_id, [])
    items.append(text)
    del items[:-8]


async def _greet_phrase(chat_id: int) -> str:
    """Фраза из базы, которой не было среди 8 последних приветствий в этом чате."""
    recent = set(_greeted.get(chat_id, []))
    tpl = ""
    for _ in range(6):
        tpl = await db.random_phrase("greet") or random.choice(GREETINGS)
        if tpl not in recent:
            break
    _remember_greet(chat_id, tpl)
    return tpl


async def greet(bot: Bot, chat, user_id: int, name: str, thread: int | None = None) -> None:
    """Приветствие новичка: примерно поровну то фраза из базы, то нейросеть в характере бота. Нейросеть не видит
    переписку (раньше заодно отвечала на чужие вопросы) и не обсуждает ник. Имя всегда кликабельное, в начале."""
    text = ""
    if random.random() < 0.5:
        system = prompts.system_prompt(chat["bot_name"], plans_persona(chat), chat["topic"], chat["title"] or "", [],
                                       await rules(chat))
        recent = [t for t in _greeted.get(chat["chat_id"], []) if "{name}" not in t]
        answer = await ai.chat_as("event", [{"role": "system", "content": system},
                                           {"role": "user", "content": prompts.greet_task(name, recent)}],
                                  max_tokens=80)
        text = prompts.drop_commas(prompts.clean_reply(answer or "", chat["bot_name"]))
        if text and name.lower() in text.lower():   # имя модель всё равно могла вставить: убираем, добавим сами
            text = re.sub(re.escape(name), "", text, flags=re.I).strip(" ,!.") or ""
        text = re.sub(r"^(?:о|оу|ооо|опа)[,!\s]+", "", text, flags=re.I).strip()   # не все с «о, ...»
        if text:
            _remember_greet(chat["chat_id"], text)
    if text:
        html_text, plain = f"{mention(user_id, name)} {esc(text)}", f"{name} {text}"
    else:
        tpl = await _greet_phrase(chat["chat_id"])
        plain = prompts.drop_commas(tpl.replace("{name}", name))
        html_text = esc(plain).replace(esc(name), mention(user_id, name), 1)
    await send_text(bot, chat, html_text, plain, thread=thread)


def plans_persona(chat) -> str:
    from bot.services import plans
    return plans.persona(chat)


async def in_character(bot: Bot, chat_id: int, situation: str, fallbacks: list[str], tail_html: str = "",
                       markup=None) -> None:
    """Сказать в чат что-то служебное, но в образе персонажа: ИИ пишет реплику по ситуации и характеру.
    Не вышло (нет ИИ или лимит): берём одну из заготовок. tail_html добавляется в конце как есть."""
    chat = await db.get_chat(chat_id)
    text = None
    if chat:
        system = prompts.system_prompt(chat["bot_name"], chat["persona"], chat["topic"], chat["title"] or "", [],
                                       await rules(chat))
        answer = await ai.chat_as("event", [{"role": "system", "content": system}, {"role": "user", "content": situation}],
                               max_tokens=160)
        text = prompts.clean_reply(answer or "", chat["bot_name"])
    text = text or random.choice(fallbacks)
    sent = await say(bot, chat_id, esc(text) + (f"\n\n{tail_html}" if tail_html else ""), markup=markup)
    if chat:
        await remember_self(bot, chat, sent, text)


async def test_reply(chat, author: str, text: str) -> str | None:
    """Пробный ответ для админа: как бот ответил бы в чате. В чат ничего не отправляется."""
    return await _ask(chat, lambda history: prompts.test_task(author, text))
