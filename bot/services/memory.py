"""Заметки о юзерах: раз в MEMORY_EVERY сообщений нейросеть перечитывает, что человек
писал, и обновляет короткую карточку (как зовут, откуда, чем увлекается).
Эти заметки бот видит, когда отвечает в чате."""

import asyncio
import logging

from bot import ai, config, db, prompts

log = logging.getLogger(__name__)

_running: set[tuple[int, int]] = set()
_tasks: set[asyncio.Task] = set()  # держим ссылки, иначе фоновую задачу может съесть сборщик мусора


def due(user) -> bool:
    return bool(config.MEMORY_EVERY) and user["msg_count"] - user["notes_at"] >= config.MEMORY_EVERY


async def _update(chat_id: int, user_id: int) -> None:
    key = (chat_id, user_id)
    if key in _running:
        return
    _running.add(key)
    try:
        user = await db.get_user(chat_id, user_id)
        if user is None:
            return
        messages = await db.user_messages(chat_id, user_id, 30)
        if len(messages) < 5:
            return
        notes = await ai.chat(prompts.memory_messages(user["name"], user["notes"], messages),
                              max_tokens=200, temperature=0.3)
        if notes:
            await db.set_notes(chat_id, user_id, " ".join(notes.split())[:300], user["msg_count"])
    except Exception:
        log.exception("Заметки о юзере %s не обновились", user_id)
    finally:
        _running.discard(key)


def maybe_update(chat_id: int, user) -> None:
    """Запускает обновление в фоне, чтобы не задерживать ответ в чате."""
    if due(user):
        task = asyncio.create_task(_update(chat_id, user["user_id"]))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
