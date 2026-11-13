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
CREATE INDEX IF NOT EXISTS history_msg ON history (chat_id, message_id);
CREATE INDEX IF NOT EXISTS history_ts ON history (chat_id, ts);

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

CREATE TABLE IF NOT EXISTS daily_stats (
    chat_id     INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL DEFAULT '',
    msgs        INTEGER NOT NULL DEFAULT 0,
    mat         INTEGER NOT NULL DEFAULT 0,   -- сообщений с матом
    laughs      INTEGER NOT NULL DEFAULT 0,   -- сколько раз над ним поржали в ответах
    PRIMARY KEY (chat_id, day, user_id)
);

CREATE TABLE IF NOT EXISTS msg_reacts (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,             -- автор сообщения
    name        TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    ts          REAL    NOT NULL,             -- когда написано сообщение
    total       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS pair_polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    user1       INTEGER NOT NULL,
    user2       INTEGER NOT NULL,
    name1       TEXT    NOT NULL,
    name2       TEXT    NOT NULL,
    message_id  INTEGER NOT NULL DEFAULT 0,
    created     REAL    NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pair_votes (
    poll_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    vote        INTEGER NOT NULL,             -- 1 огонь, 0 не верю
    PRIMARY KEY (poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS rep_points (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    points      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS rep_log (
    chat_id     INTEGER NOT NULL,
    giver       INTEGER NOT NULL,
    receiver    INTEGER NOT NULL,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS rep_log_giver ON rep_log (chat_id, giver, ts);

CREATE TABLE IF NOT EXISTS quiz_scores (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    points      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
"""

# Колонки, которых не было в первой версии. Добавляются в старую базу при запуске.
NEW_COLUMNS = {
    "chats": {
        "pairpoll": "INTEGER NOT NULL DEFAULT 1",       # «как вам пара»
        "results": "INTEGER NOT NULL DEFAULT 1",        # итоги дня
        "rep": "INTEGER NOT NULL DEFAULT 1",            # репутация
        "bday": "INTEGER NOT NULL DEFAULT 1",           # поздравления с ДР
        "results_hour": "INTEGER NOT NULL DEFAULT 23",
        "last_results": "TEXT NOT NULL DEFAULT ''",
        "last_pairpoll": "TEXT NOT NULL DEFAULT ''",
    },
    "users": {
        "birthday": "TEXT NOT NULL DEFAULT ''",         # 'MM-DD'
        "bday_year": "INTEGER NOT NULL DEFAULT 0",      # в каком году уже поздравили
    },
    "history": {
        "reply_user_id": "INTEGER NOT NULL DEFAULT 0",
    },
}

CHAT_FIELDS = {"bot_name", "aliases", "persona", "topic", "chance", "ai_share",
               "cooldown", "greet", "games", "ads", "title", "active", "last_jump",
               "pairpoll", "results", "rep", "bday", "results_hour", "last_results", "last_pairpoll"}
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
    await _migrate()
    await _db.commit()
    await _seed_phrases()


async def _migrate() -> None:
    for table, columns in NEW_COLUMNS.items():
        async with conn().execute(f"PRAGMA table_info({table})") as cur:
            have = {row[1] for row in await cur.fetchall()}
        for name, ddl in columns.items():
            if name not in have:
                await conn().execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


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
    for table in ("chats", "users", "history", "ad_sends", "couples", "daily_stats", "msg_reacts",
                  "pair_polls", "rep_points", "rep_log", "quiz_scores"):
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
                      reply_name: str = "", is_bot: bool = False, reply_user_id: int = 0) -> None:
    await conn().execute(
        "INSERT INTO history (chat_id, message_id, user_id, name, text, reply_name, is_bot, ts, reply_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (chat_id, message_id, user_id, name, text[:1000], reply_name, int(is_bot), time.time(), reply_user_id))
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


# ---------- статистика по дням ----------

async def add_daily(chat_id: int, user_id: int, name: str, mat: bool) -> None:
    await conn().execute(
        "INSERT INTO daily_stats (chat_id, day, user_id, name, msgs, mat) VALUES (?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(chat_id, day, user_id) DO UPDATE SET name = excluded.name, msgs = msgs + 1, "
        "mat = mat + excluded.mat", (chat_id, today(), user_id, name, int(mat)))
    await conn().commit()


async def add_laugh(chat_id: int, user_id: int, name: str) -> None:
    await conn().execute(
        "INSERT INTO daily_stats (chat_id, day, user_id, name, laughs) VALUES (?, ?, ?, ?, 1) "
        "ON CONFLICT(chat_id, day, user_id) DO UPDATE SET laughs = laughs + 1", (chat_id, today(), user_id, name))
    await conn().commit()


async def daily_stats(chat_id: int, day: str) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM daily_stats WHERE chat_id = ? AND day = ?", (chat_id, day)) as cur:
        return list(await cur.fetchall())


async def history_since(chat_id: int, since: float, limit: int = 2000) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT * FROM history WHERE chat_id = ? AND ts >= ? ORDER BY id DESC LIMIT ?",
            (chat_id, since, limit)) as cur:
        rows = list(await cur.fetchall())
    rows.reverse()
    return rows


async def chat_message_count(chat_id: int, since: float) -> int:
    async with conn().execute("SELECT COUNT(*) FROM history WHERE chat_id = ? AND ts >= ? AND is_bot = 0",
                              (chat_id, since)) as cur:
        return (await cur.fetchone())[0]


async def top_reply_pair(chat_id: int, since: float, bot_id: int) -> tuple[int, int, int] | None:
    """Двое, кто больше всех отвечал друг другу: (id1, id2, сколько раз)."""
    async with conn().execute(
            "SELECT MIN(user_id, reply_user_id) AS a, MAX(user_id, reply_user_id) AS b, COUNT(*) AS n "
            "FROM history WHERE chat_id = ? AND ts >= ? AND is_bot = 0 AND reply_user_id NOT IN (0, ?) "
            "AND reply_user_id != user_id GROUP BY a, b ORDER BY n DESC LIMIT 1", (chat_id, since, bot_id)) as cur:
        row = await cur.fetchone()
    return (row["a"], row["b"], row["n"]) if row else None


# ---------- реакции ----------

async def add_reaction(chat_id: int, message_id: int, delta: int | None = None, total: int | None = None) -> None:
    """Реакция на сообщение: delta (+1/-1 от одного человека) или сразу total.
    Автора и текст берём из истории, реакции на слишком старые сообщения не считаем."""
    async with conn().execute("SELECT * FROM history WHERE chat_id = ? AND message_id = ? AND is_bot = 0",
                              (chat_id, message_id)) as cur:
        src = await cur.fetchone()
    if src is None:
        return
    if total is not None:
        update, first, arg = "excluded.total", max(0, total), max(0, total)
    else:
        update, first, arg = "MAX(0, total + ?)", max(0, delta or 0), delta or 0
    params = [chat_id, message_id, src["user_id"], src["name"], src["text"], src["ts"], first]
    if total is None:
        params.append(arg)
    await conn().execute(
        "INSERT INTO msg_reacts (chat_id, message_id, user_id, name, text, ts, total) VALUES (?, ?, ?, ?, ?, ?, ?) "
        f"ON CONFLICT(chat_id, message_id) DO UPDATE SET total = {update}", params)
    await conn().commit()


async def top_reacted(chat_id: int, since: float) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM msg_reacts WHERE chat_id = ? AND ts >= ? AND total > 0 "
                              "ORDER BY total DESC LIMIT 1", (chat_id, since)) as cur:
        return await cur.fetchone()


async def reacts_by_user(chat_id: int, since: float) -> dict[int, int]:
    async with conn().execute("SELECT user_id, SUM(total) AS n FROM msg_reacts WHERE chat_id = ? AND ts >= ? "
                              "GROUP BY user_id", (chat_id, since)) as cur:
        return {r["user_id"]: r["n"] for r in await cur.fetchall()}


# ---------- «как вам пара» ----------

async def create_poll(chat_id: int, user1: int, user2: int, name1: str, name2: str) -> int:
    cur = await conn().execute(
        "INSERT INTO pair_polls (chat_id, user1, user2, name1, name2, created) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, user1, user2, name1, name2, time.time()))
    await conn().commit()
    return cur.lastrowid


async def get_poll(poll_id: int) -> aiosqlite.Row | None:
    async with conn().execute("SELECT * FROM pair_polls WHERE id = ?", (poll_id,)) as cur:
        return await cur.fetchone()


async def set_poll_message(poll_id: int, message_id: int) -> None:
    await conn().execute("UPDATE pair_polls SET message_id = ? WHERE id = ?", (message_id, poll_id))
    await conn().commit()


async def vote_poll(poll_id: int, user_id: int, vote: int) -> None:
    await conn().execute("INSERT OR REPLACE INTO pair_votes (poll_id, user_id, vote) VALUES (?, ?, ?)",
                         (poll_id, user_id, vote))
    await conn().commit()


async def poll_counts(poll_id: int) -> tuple[int, int]:
    async with conn().execute("SELECT SUM(vote = 1) AS y, SUM(vote = 0) AS n FROM pair_votes WHERE poll_id = ?",
                              (poll_id,)) as cur:
        row = await cur.fetchone()
    return row["y"] or 0, row["n"] or 0


async def polls_to_close(older_than: float) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM pair_polls WHERE closed = 0 AND created <= ?", (older_than,)) as cur:
        return list(await cur.fetchall())


async def close_poll(poll_id: int) -> None:
    await conn().execute("UPDATE pair_polls SET closed = 1 WHERE id = ?", (poll_id,))
    await conn().commit()


# ---------- репутация ----------

async def rep_allowed(chat_id: int, giver: int, receiver: int, now: float) -> bool:
    """Одному и тому же человеку не чаще раза в час, всего не больше 30 в сутки."""
    async with conn().execute(
            "SELECT SUM(receiver = ? AND ts >= ?) AS same, COUNT(*) AS total FROM rep_log "
            "WHERE chat_id = ? AND giver = ? AND ts >= ?",
            (receiver, now - 3600, chat_id, giver, now - 86400)) as cur:
        row = await cur.fetchone()
    return not (row["same"] or 0) and (row["total"] or 0) < 30


async def rep_change(chat_id: int, giver: int, receiver: int, delta: int) -> int:
    now = time.time()
    await conn().execute("INSERT INTO rep_log (chat_id, giver, receiver, ts) VALUES (?, ?, ?, ?)",
                         (chat_id, giver, receiver, now))
    await conn().execute("DELETE FROM rep_log WHERE ts < ?", (now - 2 * 86400,))
    await conn().execute(
        "INSERT INTO rep_points (chat_id, user_id, points) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET points = points + excluded.points", (chat_id, receiver, delta))
    await conn().commit()
    return await rep_get(chat_id, receiver)


async def rep_get(chat_id: int, user_id: int) -> int:
    async with conn().execute("SELECT points FROM rep_points WHERE chat_id = ? AND user_id = ?",
                              (chat_id, user_id)) as cur:
        row = await cur.fetchone()
    return row["points"] if row else 0


async def rep_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT r.user_id, r.points, COALESCE(u.name, 'кто-то') AS name FROM rep_points r "
            "LEFT JOIN users u ON u.chat_id = r.chat_id AND u.user_id = r.user_id "
            "WHERE r.chat_id = ? AND r.points != 0 ORDER BY r.points DESC LIMIT ?", (chat_id, limit)) as cur:
        return list(await cur.fetchall())


# ---------- викторина ----------

async def quiz_add(chat_id: int, user_id: int, points: int) -> None:
    await conn().execute(
        "INSERT INTO quiz_scores (chat_id, user_id, points) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET points = points + excluded.points", (chat_id, user_id, points))
    await conn().commit()


async def quiz_top(chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    async with conn().execute(
            "SELECT q.user_id, q.points, COALESCE(u.name, 'кто-то') AS name FROM quiz_scores q "
            "LEFT JOIN users u ON u.chat_id = q.chat_id AND u.user_id = q.user_id "
            "WHERE q.chat_id = ? ORDER BY q.points DESC LIMIT ?", (chat_id, limit)) as cur:
        return list(await cur.fetchall())


# ---------- дни рождения ----------

async def set_birthday(chat_id: int, user_id: int, mmdd: str) -> None:
    await conn().execute("UPDATE users SET birthday = ? WHERE chat_id = ? AND user_id = ?", (mmdd, chat_id, user_id))
    await conn().commit()


async def birthdays_today(chat_id: int, mmdd: str, year: int) -> list[aiosqlite.Row]:
    """Именинники, которых ещё не поздравили и кто появлялся в чате за последние 2 месяца."""
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND birthday = ? AND bday_year != ? AND last_seen >= ?",
            (chat_id, mmdd, year, time.time() - 60 * 86400)) as cur:
        return list(await cur.fetchall())


async def mark_bday(chat_id: int, user_id: int, year: int) -> None:
    await conn().execute("UPDATE users SET bday_year = ? WHERE chat_id = ? AND user_id = ?", (year, chat_id, user_id))
    await conn().commit()


async def all_birthdays(chat_id: int) -> list[aiosqlite.Row]:
    async with conn().execute("SELECT * FROM users WHERE chat_id = ? AND birthday != ''", (chat_id,)) as cur:
        return list(await cur.fetchall())


async def find_user(chat_id: int, query: str) -> aiosqlite.Row | None:
    """Ищет участника по @username или по имени (первое совпадение среди недавно писавших)."""
    q = query.strip().lstrip("@").lower()
    if not q:
        return None
    async with conn().execute(
            "SELECT * FROM users WHERE chat_id = ? AND (lower(username) = ? OR lower(name) = ? OR lower(name) LIKE ?) "
            "ORDER BY last_seen DESC LIMIT 1", (chat_id, q, q, q + "%")) as cur:
        return await cur.fetchone()
