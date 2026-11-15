"""Хранение экономики в общей базе. Кошелёк и питомец общие на человека во всех чатах:
профиль и магазин живут в личке бота, а в чатах показываются те же монеты и тот же питомец.
Топы в чате считаются среди тех, кого бот видел в этом чате (таблица users)."""

import time

import aiosqlite

from bot.db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS eco_users (
    user_id     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL DEFAULT '',
    coins       INTEGER NOT NULL DEFAULT 0,
    xp          INTEGER NOT NULL DEFAULT 0,
    level       INTEGER NOT NULL DEFAULT 1,
    last_award  REAL    NOT NULL DEFAULT 0,      -- когда последний раз дали опыт за сообщение
    bonus_day   TEXT    NOT NULL DEFAULT '',     -- день последнего бонуса
    streak      INTEGER NOT NULL DEFAULT 0,      -- сколько дней подряд забирал бонус
    earned      INTEGER NOT NULL DEFAULT 0,      -- всего заработано монет (для статистики)
    created     REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS eco_users_coins ON eco_users (coins DESC);

CREATE TABLE IF NOT EXISTS eco_pets (
    user_id     INTEGER PRIMARY KEY,
    owner       TEXT    NOT NULL DEFAULT '',
    species     TEXT    NOT NULL,                -- ключ из catalog.PETS
    name        TEXT    NOT NULL DEFAULT '',     -- кличка
    xp          INTEGER NOT NULL DEFAULT 0,
    satiety     REAL    NOT NULL DEFAULT 80,     -- сытость 0-100, падает со временем
    fed_at      REAL    NOT NULL DEFAULT 0,      -- когда считали сытость в последний раз
    fed_by      TEXT    NOT NULL DEFAULT '',     -- кто кормил последним и чем: Иван · Лосось 🍣
    warned      INTEGER NOT NULL DEFAULT 0,      -- уже написали хозяину, что питомец проголодался
    created     REAL    NOT NULL
);
"""

_IN_CHAT = "user_id IN (SELECT user_id FROM users WHERE chat_id = ?)"


async def init() -> None:
    await conn().executescript(SCHEMA)
    await conn().commit()


# ---------- кошелёк ----------

async def wallet(user_id: int, name: str = "") -> aiosqlite.Row:
    await conn().execute("INSERT OR IGNORE INTO eco_users (user_id, name, created) VALUES (?, ?, ?)",
                         (user_id, name, time.time()))
    if name:
        await conn().execute("UPDATE eco_users SET name = ? WHERE user_id = ? AND name != ?", (name, user_id, name))
    await conn().commit()
    async with conn().execute("SELECT * FROM eco_users WHERE user_id = ?", (user_id,)) as cur:
        return await cur.fetchone()


async def update_wallet(user_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE eco_users SET {sets} WHERE user_id = ?", (*fields.values(), user_id))
    await conn().commit()


async def add_coins(user_id: int, amount: int, name: str = "") -> int:
    """Прибавляет (или отнимает) монеты. Возвращает новый баланс."""
    await wallet(user_id, name)
    await conn().execute("UPDATE eco_users SET coins = MAX(0, coins + ?), earned = earned + MAX(0, ?) "
                         "WHERE user_id = ?", (amount, amount, user_id))
    await conn().commit()
    return (await wallet(user_id))["coins"]


async def spend(user_id: int, amount: int) -> bool:
    """Списывает монеты, только если их хватает (одним запросом, без гонок)."""
    cur = await conn().execute("UPDATE eco_users SET coins = coins - ? WHERE user_id = ? AND coins >= ?",
                               (amount, user_id, amount))
    await conn().commit()
    return cur.rowcount > 0


async def rich_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute(f"SELECT * FROM eco_users WHERE {_IN_CHAT} AND coins > 0 ORDER BY coins DESC LIMIT ?",
                              (chat_id, limit)) as cur:
        return list(await cur.fetchall())


async def level_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute(f"SELECT * FROM eco_users WHERE {_IN_CHAT} AND xp > 0 ORDER BY xp DESC LIMIT ?",
                              (chat_id, limit)) as cur:
        return list(await cur.fetchall())


async def totals() -> dict:
    """Для админки: сколько людей с монетами, сколько монет и питомцев всего."""
    async with conn().execute("SELECT COUNT(*), COALESCE(SUM(coins), 0) FROM eco_users") as cur:
        people, coins = await cur.fetchone()
    async with conn().execute("SELECT COUNT(*) FROM eco_pets") as cur:
        pets = (await cur.fetchone())[0]
    return {"people": people, "coins": coins, "pets": pets}


# ---------- питомцы ----------

async def pet(user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM eco_pets WHERE user_id = ?", (user_id,)) as cur:
        return await cur.fetchone()


async def set_pet(user_id: int, owner: str, species: str, name: str) -> None:
    """Новый питомец (старый заменяется: это апгрейд)."""
    now = time.time()
    await conn().execute("INSERT OR REPLACE INTO eco_pets (user_id, owner, species, name, xp, satiety, fed_at, created) "
                         "VALUES (?, ?, ?, ?, 0, 80, ?, ?)", (user_id, owner, species, name, now, now))
    await conn().commit()


async def update_pet(user_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE eco_pets SET {sets} WHERE user_id = ?", (*fields.values(), user_id))
    await conn().commit()


async def delete_pet(user_id: int) -> None:
    await conn().execute("DELETE FROM eco_pets WHERE user_id = ?", (user_id,))
    await conn().commit()


async def pets_in_chat(chat_id: int) -> list[aiosqlite.Row]:
    async with conn().execute(f"SELECT * FROM eco_pets WHERE {_IN_CHAT}", (chat_id,)) as cur:
        return list(await cur.fetchall())


async def all_pets() -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM eco_pets") as cur:
        return list(await cur.fetchall())
