"""Хранение экономики в общей базе: кошельки и питомцы. Таблицы создаются здесь же при запуске."""

import time

import aiosqlite

from bot.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    coins       INTEGER NOT NULL DEFAULT 0,
    xp          INTEGER NOT NULL DEFAULT 0,
    level       INTEGER NOT NULL DEFAULT 1,
    last_award  REAL    NOT NULL DEFAULT 0,      -- когда последний раз дали опыт за сообщение
    bonus_day   TEXT    NOT NULL DEFAULT '',     -- день последнего бонуса
    streak      INTEGER NOT NULL DEFAULT 0,      -- сколько дней подряд забирал бонус
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS wallet_coins ON wallet (chat_id, coins DESC);

CREATE TABLE IF NOT EXISTS pets (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    owner       TEXT    NOT NULL DEFAULT '',
    species     TEXT    NOT NULL,                -- ключ из catalog.PETS
    name        TEXT    NOT NULL DEFAULT '',     -- кличка
    xp          INTEGER NOT NULL DEFAULT 0,
    satiety     REAL    NOT NULL DEFAULT 80,     -- сытость 0-100, падает со временем
    fed_at      REAL    NOT NULL DEFAULT 0,      -- когда считали сытость в последний раз
    fed_by      TEXT    NOT NULL DEFAULT '',     -- кто кормил последним и чем: «Иван · Лосось 🍣»
    warned      INTEGER NOT NULL DEFAULT 0,      -- уже написали в чат, что питомец проголодался
    created     REAL    NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
"""


async def init() -> None:
    await conn().executescript(SCHEMA)
    await conn().commit()


# ---------- кошелёк ----------

async def wallet(chat_id: int, user_id: int, name: str = "") -> aiosqlite.Row:
    await conn().execute("INSERT OR IGNORE INTO wallet (chat_id, user_id, name) VALUES (?, ?, ?)",
                         (chat_id, user_id, name))
    if name:
        await conn().execute("UPDATE wallet SET name = ? WHERE chat_id = ? AND user_id = ?", (name, chat_id, user_id))
    await conn().commit()
    async with conn().execute("SELECT * FROM wallet WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
        return await cur.fetchone()


async def update_wallet(chat_id: int, user_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE wallet SET {sets} WHERE chat_id = ? AND user_id = ?",
                         (*fields.values(), chat_id, user_id))
    await conn().commit()


async def add_coins(chat_id: int, user_id: int, amount: int, name: str = "") -> int:
    """Прибавляет (или отнимает) монеты. Возвращает новый баланс."""
    await wallet(chat_id, user_id, name)
    await conn().execute("UPDATE wallet SET coins = MAX(0, coins + ?) WHERE chat_id = ? AND user_id = ?",
                         (amount, chat_id, user_id))
    await conn().commit()
    return (await wallet(chat_id, user_id))["coins"]


async def spend(chat_id: int, user_id: int, amount: int) -> bool:
    """Списывает монеты, только если их хватает."""
    cur = await conn().execute("UPDATE wallet SET coins = coins - ? WHERE chat_id = ? AND user_id = ? AND coins >= ?",
                               (amount, chat_id, user_id, amount))
    await conn().commit()
    return cur.rowcount > 0


async def rich_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM wallet WHERE chat_id = ? AND coins > 0 ORDER BY coins DESC LIMIT ?",
                              (chat_id, limit)) as cur:
        return list(await cur.fetchall())


async def level_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM wallet WHERE chat_id = ? AND xp > 0 ORDER BY xp DESC LIMIT ?",
                              (chat_id, limit)) as cur:
        return list(await cur.fetchall())


# ---------- питомцы ----------

async def pet(chat_id: int, user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM pets WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)) as cur:
        return await cur.fetchone()


async def set_pet(chat_id: int, user_id: int, owner: str, species: str, name: str) -> None:
    """Новый питомец (старый заменяется: это апгрейд)."""
    now = time.time()
    await conn().execute("INSERT OR REPLACE INTO pets (chat_id, user_id, owner, species, name, xp, satiety, fed_at, "
                         "created) VALUES (?, ?, ?, ?, ?, 0, 80, ?, ?)", (chat_id, user_id, owner, species, name, now, now))
    await conn().commit()


async def update_pet(chat_id: int, user_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE pets SET {sets} WHERE chat_id = ? AND user_id = ?", (*fields.values(), chat_id, user_id))
    await conn().commit()


async def pets_in_chat(chat_id: int) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM pets WHERE chat_id = ?", (chat_id,)) as cur:
        return list(await cur.fetchall())
