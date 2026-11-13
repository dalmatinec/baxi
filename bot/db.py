"""База SQLite: чаты, юзеры, история сообщений, фразы, реклама, расход на ИИ."""

import json
import time
from datetime import datetime

import aiosqlite

from bot import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    bot_name    TEXT    NOT NULL,
    aliases     TEXT    NOT NULL DEFAULT '',
    persona     TEXT    NOT NULL,
    topic       TEXT    NOT NULL,
    chance      REAL    NOT NULL,
    ai_share    REAL    NOT NULL,
    cooldown    INTEGER NOT NULL,
    greet       INTEGER NOT NULL DEFAULT 1,
    games       INTEGER NOT NULL DEFAULT 1,
    ads         INTEGER NOT NULL DEFAULT 1,
    last_jump   REAL    NOT NULL DEFAULT 0,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    username    TEXT    NOT NULL DEFAULT '',
    msg_count   INTEGER NOT NULL DEFAULT 0,
    last_seen   REAL    NOT NULL DEFAULT 0,
    notes       TEXT    NOT NULL DEFAULT '',
    notes_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    reply_name  TEXT    NOT NULL DEFAULT '',
    is_bot      INTEGER NOT NULL DEFAULT 0,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS history_chat ON history (chat_id, id);

CREATE TABLE IF NOT EXISTS phrases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,          -- text | sticker | gif
    content     TEXT    NOT NULL,          -- текст или file_id
    created_at  REAL    NOT NULL,
    UNIQUE (kind, content)
);

CREATE TABLE IF NOT EXISTS ads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    media_kind  TEXT    NOT NULL DEFAULT '',   -- '' | photo | video | gif
    file_id     TEXT    NOT NULL DEFAULT '',
    text_html   TEXT    NOT NULL DEFAULT '',
    buttons     TEXT    NOT NULL DEFAULT '[]', -- [[["текст","ссылка"], ...], ...]
    interval    INTEGER NOT NULL DEFAULT 180,  -- минуты
    enabled     INTEGER NOT NULL DEFAULT 1,
    delete_prev INTEGER NOT NULL DEFAULT 1,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS ad_sends (
    ad_id       INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    last_sent   REAL    NOT NULL,
    message_id  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ad_id, chat_id)
);

CREATE TABLE IF NOT EXISTS spend (
    day         TEXT    PRIMARY KEY,
    usd         REAL    NOT NULL DEFAULT 0,
    requests    INTEGER NOT NULL DEFAULT 0,
    tok_in      INTEGER NOT NULL DEFAULT 0,
    tok_out     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS couples (
    chat_id     INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    user1       INTEGER NOT NULL,
    user2       INTEGER NOT NULL,
    PRIMARY KEY (chat_id, day)
);
"""

CHAT_FIELDS = {"bot_name", "aliases", "persona", "topic", "chance", "ai_share",
               "cooldown", "greet", "games", "ads", "title", "active", "last_jump"}
AD_FIELDS = {"title", "media_kind", "file_id", "text_html", "buttons", "interval",
             "enabled", "delete_prev"}

_db: aiosqlite.Connection | None = None


def today() -> str:
    return datetime.now(config.TZ).strftime("%Y-%m-%d")


async def connect() -> None:
    global _db
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.executescript(SCHEMA)
    await _db.commit()
    await _seed_phrases()


async def close() -> None:
    if _db is not None:
        await _db.close()


def conn() -> aiosqlite.Connection:
    assert _db is not None, "база не открыта"
    return _db


async def _seed_phrases() -> None:
    from bot.phrases_seed import PHRASES
    async with conn().execute("SELECT COUNT(*) FROM phrases") as cur:
        if (await cur.fetchone())[0]:
            return
    now = time.time()
    await conn().executemany(
        "INSERT OR IGNORE INTO phrases (kind, content, created_at) VALUES ('text', ?, ?)",
        [(p, now) for p in PHRASES])
    await conn().commit()


# ---------- чаты ----------

async def ensure_chat(chat_id: int, title: str) -> aiosqlite.Row:
    await conn().execute(
        """INSERT INTO chats (chat_id, title, bot_name, persona, topic, chance, ai_share, cooldown, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, active = 1""",
        (chat_id, title, config.DEFAULT_NAME, config.DEFAULT_PERSONA, config.DEFAULT_TOPIC,
         config.DEFAULT_CHANCE, config.DEFAULT_AI_SHARE, config.DEFAULT_COOLDOWN, time.time()))
    await conn().commit()
    return await get_chat(chat_id)


async def get_chat(chat_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)) as cur:
        return await cur.fetchone()


async def list_chats(active_only: bool = True) -> list[aiosqlite.Row]:
    sql = "SELECT * FROM chats" + (" WHERE active = 1" if active_only else "") + " ORDER BY title"
    async with conn().execute(sql) as cur:
        return list(await cur.fetchall())


async def update_chat(chat_id: int, **fields) -> None:
    bad = set(fields) - CHAT_FIELDS
    if bad:
        raise ValueError(f"неизвестные поля чата: {bad}")
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE chats SET {sets} WHERE chat_id = ?", (*fields.values(), chat_id))
    await conn().commit()


async def migrate_chat(old_id: int, new_id: int) -> None:
    """Группа стала супергруппой: у неё новый ID."""
    for table in ("chats", "users", "history", "ad_sends", "couples"):
        await conn().execute(f"UPDATE OR IGNORE {table} SET chat_id = ? WHERE chat_id = ?", (new_id, old_id))
    await conn().commit()


# ---------- юзеры ----------

async def touch_user(chat_id: int, user_id: int, name: str, username: str) -> aiosqlite.Row:
    await conn().execute(
        """INSERT INTO users (chat_id, user_id, name, username, msg_count, last_seen)
           VALUES (?, ?, ?, ?, 1, ?)
           ON CONFLICT(chat_id, user_id) DO UPDATE SET
               name = excluded.name, username = excluded.username,
               msg_count = msg_count + 1, last_seen = excluded.last_seen""",
        (chat_id, user_id, name, username, time.time()))
    await conn().commit()
    return await get_user(chat_id, user_id)


async def add_user_silently(chat_id: int, user_id: int, name: str, username: str) -> None:
    """Новичок вступил: запоминаем, но сообщений у него ещё нет."""
    await conn().execute(
        """INSERT INTO users (chat_id, user_id, name, username, last_seen) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(chat_id, user_id) DO UPDATE SET name = excluded.name, username = excluded.username""",
        (chat_id, user_id, name, username, time.time()))
    await conn().commit()


async def get_user(chat_id: int, user_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM users WHERE chat_id = ? AND user_id = ?",
                              (chat_id, user_id)) as cur:
        return await cur.fetchone()


async def users_by_ids(chat_id: int, ids: list[int]) -> list[aiosqlite.Row]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    async with conn().execute(f"SELECT * FROM users WHERE chat_id = ? AND user_id IN ({marks})",
                              (chat_id, *ids)) as cur:
        return list(await cur.fetchall())


async def active_users(chat_id: int, days: int = 7, limit: int = 300) -> list[aiosqlite.Row]:
    """Те, кто писал за последние дни. Только из них берутся рандомы в играх."""
    since = time.time() - days * 86400
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND last_seen >= ? AND msg_count > 0 "
            "ORDER BY last_seen DESC LIMIT ?", (chat_id, since, limit)) as cur:
        return list(await cur.fetchall())


async def set_notes(chat_id: int, user_id: int, notes: str, at_count: int) -> None:
    await conn().execute("UPDATE users SET notes = ?, notes_at = ? WHERE chat_id = ? AND user_id = ?",
                         (notes, at_count, chat_id, user_id))
    await conn().commit()


# ---------- история ----------

async def add_history(chat_id: int, message_id: int, user_id: int, name: str, text: str,
                      reply_name: str = "", is_bot: bool = False) -> None:
    await conn().execute(
        "INSERT INTO history (chat_id, message_id, user_id, name, text, reply_name, is_bot, ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (chat_id, message_id, user_id, name, text[:1000], reply_name, int(is_bot), time.time()))
    # держим в базе только последние HISTORY_KEEP сообщений чата
    await conn().execute(
        "DELETE FROM history WHERE chat_id = ? AND id <= "
        "(SELECT id FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?)",
        (chat_id, chat_id, config.HISTORY_KEEP))
    await conn().commit()


async def recent_history(chat_id: int, limit: int) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT * FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)) as cur:
        rows = list(await cur.fetchall())
    rows.reverse()
    return rows


async def user_messages(chat_id: int, user_id: int, limit: int) -> list[str]:
    async with conn().execute(
            "SELECT text FROM history WHERE chat_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit)) as cur:
        rows = await cur.fetchall()
    return [r["text"] for r in reversed(rows)]


async def clear_memory(chat_id: int) -> None:
    await conn().execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))
    await conn().execute("UPDATE users SET notes = '', notes_at = 0 WHERE chat_id = ?", (chat_id,))
    await conn().commit()


# ---------- фразы, стикеры, гифки ----------

async def add_phrase(kind: str, content: str) -> bool:
    cur = await conn().execute("INSERT OR IGNORE INTO phrases (kind, content, created_at) VALUES (?, ?, ?)",
                               (kind, content, time.time()))
    await conn().commit()
    return cur.rowcount > 0


async def random_phrase(kind: str) -> str | None:
    async with conn().execute("SELECT content FROM phrases WHERE kind = ? ORDER BY RANDOM() LIMIT 1",
                              (kind,)) as cur:
        row = await cur.fetchone()
    return row["content"] if row else None


async def list_phrases(kind: str, offset: int, limit: int) -> tuple[list[aiosqlite.Row], int]:
    async with conn().execute("SELECT COUNT(*) FROM phrases WHERE kind = ?", (kind,)) as cur:
        total = (await cur.fetchone())[0]
    async with conn().execute("SELECT * FROM phrases WHERE kind = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                              (kind, limit, offset)) as cur:
        return list(await cur.fetchall()), total


async def count_phrases() -> dict[str, int]:
    async with conn().execute("SELECT kind, COUNT(*) AS n FROM phrases GROUP BY kind") as cur:
        return {r["kind"]: r["n"] for r in await cur.fetchall()}


async def get_phrase(phrase_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM phrases WHERE id = ?", (phrase_id,)) as cur:
        return await cur.fetchone()


async def delete_phrase(phrase_id: int) -> None:
    await conn().execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))
    await conn().commit()


# ---------- реклама ----------

async def create_ad(title: str, media_kind: str, file_id: str, text_html: str,
                    buttons: list, interval: int) -> int:
    cur = await conn().execute(
        "INSERT INTO ads (title, media_kind, file_id, text_html, buttons, interval, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, media_kind, file_id, text_html, json.dumps(buttons, ensure_ascii=False), interval, time.time()))
    await conn().commit()
    return cur.lastrowid


async def get_ad(ad_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM ads WHERE id = ?", (ad_id,)) as cur:
        return await cur.fetchone()


async def list_ads(enabled_only: bool = False) -> list[aiosqlite.Row]:
    sql = "SELECT * FROM ads" + (" WHERE enabled = 1" if enabled_only else "") + " ORDER BY id"
    async with conn().execute(sql) as cur:
        return list(await cur.fetchall())


async def update_ad(ad_id: int, **fields) -> None:
    bad = set(fields) - AD_FIELDS
    if bad:
        raise ValueError(f"неизвестные поля рекламы: {bad}")
    if "buttons" in fields and not isinstance(fields["buttons"], str):
        fields["buttons"] = json.dumps(fields["buttons"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in fields)
    await conn().execute(f"UPDATE ads SET {sets} WHERE id = ?", (*fields.values(), ad_id))
    await conn().commit()


async def delete_ad(ad_id: int) -> None:
    await conn().execute("DELETE FROM ads WHERE id = ?", (ad_id,))
    await conn().execute("DELETE FROM ad_sends WHERE ad_id = ?", (ad_id,))
    await conn().commit()


async def get_ad_send(ad_id: int, chat_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM ad_sends WHERE ad_id = ? AND chat_id = ?", (ad_id, chat_id)) as cur:
        return await cur.fetchone()


async def set_ad_send(ad_id: int, chat_id: int, message_id: int) -> None:
    await conn().execute(
        "INSERT INTO ad_sends (ad_id, chat_id, last_sent, message_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(ad_id, chat_id) DO UPDATE SET last_sent = excluded.last_sent, message_id = excluded.message_id",
        (ad_id, chat_id, time.time(), message_id))
    await conn().commit()


# ---------- расход на ИИ ----------

async def spent_today() -> float:
    async with conn().execute("SELECT usd FROM spend WHERE day = ?", (today(),)) as cur:
        row = await cur.fetchone()
    return row["usd"] if row else 0.0


async def add_spend(usd: float, tok_in: int, tok_out: int) -> None:
    await conn().execute(
        "INSERT INTO spend (day, usd, requests, tok_in, tok_out) VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(day) DO UPDATE SET usd = usd + excluded.usd, requests = requests + 1, "
        "tok_in = tok_in + excluded.tok_in, tok_out = tok_out + excluded.tok_out",
        (today(), usd, tok_in, tok_out))
    await conn().commit()


async def spend_report(days: int = 30) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM spend ORDER BY day DESC LIMIT ?", (days,)) as cur:
        return list(await cur.fetchall())


# ---------- игры ----------

async def get_couple(chat_id: int, day: str) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM couples WHERE chat_id = ? AND day = ?", (chat_id, day)) as cur:
        return await cur.fetchone()


async def set_couple(chat_id: int, day: str, user1: int, user2: int) -> None:
    await conn().execute("INSERT OR REPLACE INTO couples (chat_id, day, user1, user2) VALUES (?, ?, ?, ?)",
                         (chat_id, day, user1, user2))
    await conn().commit()
