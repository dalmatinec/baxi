"""Тексты запросов к нейросети. Здесь задаётся, как бот себя ведёт.
Модуль без Telegram-зависимостей, чтобы его было легко проверять тестами."""

import re

STYLE = (
    "Как писать:\n"
    "- как живой человек в телеграм-чате: коротко, обычно до 15 слов, максимум 2 предложения\n"
    "- строчными буквами, без точки в конце, без кавычек и без своего имени в начале\n"
    "- можно сленг, шутки, подколы и мат по ситуации, эмодзи редко\n"
    "- не пиши как помощник: не предлагай помощь, не извиняйся, не читай нотации, не задавай по три вопроса\n"
    "- отвечай по смыслу последних сообщений, обращайся к людям по имени, если уместно\n"
    "- подкалывать можно, но без оскорблений по национальности, религии и без угроз\n"
    "- не выдумывай факты о людях, которых нет в заметках и переписке"
)


def system_prompt(bot_name: str, persona: str, topic: str, title: str, notes: list[str]) -> str:
    parts = [
        f"Ты {bot_name}, обычный участник телеграм-чата «{title}».",
        f"Тема чата: {topic}.",
        f"Твой характер: {persona}.",
        STYLE,
    ]
    if notes:
        parts.append("Что ты помнишь об участниках:\n" + "\n".join(f"- {n}" for n in notes))
    return "\n\n".join(parts)


def format_history(rows, bot_name: str) -> str:
    """rows: записи истории с полями name, text, reply_name, is_bot."""
    lines = []
    for r in rows:
        who = f"{bot_name} (это ты)" if r["is_bot"] else r["name"]
        to = f" → {r['reply_name']}" if r["reply_name"] else ""
        text = " ".join(r["text"].split())
        lines.append(f"{who}{to}: {text}")
    return "\n".join(lines) if lines else "(в чате пока тихо)"


def reply_task(history: str, author: str, text: str) -> str:
    return (f"Последние сообщения чата:\n{history}\n\n"
            f"{author} обратился к тебе: «{text}»\n"
            f"Напиши свой ответ {author} одной репликой.")


def jump_task(history: str, author: str, text: str) -> str:
    return (f"Последние сообщения чата:\n{history}\n\n"
            f"Тебя не звали, но ты решил влезть в разговор и ответить на сообщение {author}: «{text}»\n"
            f"Напиши одну короткую реплику по теме разговора.")


def greet_task(name: str, history: str) -> str:
    return (f"Последние сообщения чата:\n{history}\n\n"
            f"В чат только что вступил новый человек, его зовут {name}. "
            f"Поздоровайся с ним по-своему, в своём характере, одной-двумя фразами. "
            f"Каждый раз здоровайся по-новому, без шаблонных «добро пожаловать».")


def memory_messages(name: str, old_notes: str, messages: list[str]) -> list[dict]:
    text = "\n".join(f"- {m}" for m in messages)
    return [
        {"role": "system", "content":
            "Ты ведёшь короткие заметки об участниках чата. Пиши только факты, которые человек "
            "сам сообщил или которые явно видны: как зовут или как называть, откуда, чем занимается, "
            "увлечения, прозвища, манера общения. До 250 символов, одной строкой, без оценок и домыслов. "
            "Если нового ничего нет, верни старые заметки без изменений."},
        {"role": "user", "content":
            f"Участник: {name}\nСтарые заметки: {old_notes or 'нет'}\n"
            f"Его последние сообщения:\n{text}\n\nОбновлённые заметки:"},
    ]


_PREFIX = re.compile(r"^\s*[\w\s]{1,30}\s*(\(это ты\))?\s*:\s+")


def clean_reply(text: str, bot_name: str, limit: int = 600) -> str:
    """Приводит ответ модели к виду реплики в чате."""
    text = (text or "").strip()
    # модель иногда пишет «Марат: ...», убираем своё имя в начале
    if text.lower().startswith(bot_name.lower()):
        text = _PREFIX.sub("", text, count=1)
    text = text.strip().strip("«»\"'").strip()
    # @all, @everyone и т.п. не нужны
    text = re.sub(r"@(all|everyone|here)\b", "", text, flags=re.I).strip()
    if len(text) > limit:
        cut = text[:limit]
        text = cut[: cut.rfind(" ")] if " " in cut else cut
    return text
