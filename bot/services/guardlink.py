"""Связь Бакси с модератором (dalmatinec/baxi-guard).

Модератор присылает события (warn, unwarn, mute, unmute, ban, unban, kick, spam) в POST /v1/events
(сервер в services/api.py). Здесь они запоминаются, и Бакси ими пользуется:
  * в /me у человека «⚠️ предупреждения 2/3»;
  * замученному и забаненному не отвечает;
  * бан, мут или кик убирает человека из текущих игр (кости) и списков (зазывала, пара дня);
  * в итогах дня строка «🛡 за день: 2 мута, 3 предупреждения»;
  * если админ включил, подкалывает наказанного в своём характере.
Предупреждения репутацию не трогают.

Ещё три события не про наказания:
  * greet_mode: в чате включено (on=true) или выключено приветствие модератора. Пока включено, Бакси сам
    на вход новичка не здоровается, а ждёт join;
  * join: модератор поприветствовал новичка (после капчи, если она есть), Бакси добавляет свою фразу;
  * nick: человек купил в модераторе свой ник (head, body, tail в HTML), Бакси показывает его во всех
    упоминаниях. Пустой body: ник убран.
Монеты за ник модератор списывает через POST /v1/coins/spend (см. services/api.py).

Модератора Бакси спрашивает сам (GUARD_API_URL) только для экрана «🛡 Модерация» в карточке чата."""

import logging
import random
import time
import unicodedata

import httpx

from bot import config, db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS guard_state (
    chat_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    warns         INTEGER NOT NULL DEFAULT 0,
    warn_limit    INTEGER NOT NULL DEFAULT 3,
    muted_until   INTEGER NOT NULL DEFAULT 0,     -- 0 нет, -1 навсегда, иначе до
    banned_until  INTEGER NOT NULL DEFAULT 0,     -- 0 нет, -1 навсегда, иначе до
    updated       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS guard_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    by_id    INTEGER NOT NULL DEFAULT 0,
    type     TEXT    NOT NULL,
    until    INTEGER NOT NULL DEFAULT 0,
    reason   TEXT    NOT NULL DEFAULT '',
    ts       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS guard_events_chat ON guard_events (chat_id, ts);
CREATE TABLE IF NOT EXISTS guard_chats (
    chat_id  INTEGER PRIMARY KEY,
    greets   INTEGER NOT NULL DEFAULT 0,          -- приветствие модератора включено: сами не здороваемся
    updated  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS guard_nicks (
    user_id  INTEGER PRIMARY KEY,
    head     TEXT    NOT NULL DEFAULT '',         -- премиум-эмодзи перед ником (HTML)
    body     TEXT    NOT NULL DEFAULT '',         -- сам ник с жирным, курсивом и т.п. (HTML, внутри ссылки)
    tail     TEXT    NOT NULL DEFAULT '',         -- премиум-эмодзи после ника
    plain    TEXT    NOT NULL DEFAULT '',
    updated  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS guard_spends (
    ref      TEXT    PRIMARY KEY,                 -- номер списания от модератора: повтор не спишет дважды
    user_id  INTEGER NOT NULL,
    amount   INTEGER NOT NULL,
    reason   TEXT    NOT NULL DEFAULT '',
    ts       INTEGER NOT NULL
);
"""

EVENT_TYPES = ("warn", "unwarn", "mute", "unmute", "ban", "unban", "kick", "spam", "join", "greet_mode", "nick")
SIGNALS = ("join", "greet_mode", "nick")   # не наказания: в историю не пишутся
GREET_COOLDOWN = 20        # фраза на вход не чаще раза в 20 секунд на чат (наплыв не превращается в стену)
PUNISH = ("mute", "ban", "kick")
KEEP_DAYS = 30
TEASE_COOLDOWN = 600       # подкалывает не чаще раза в 10 минут на чат
TEASE_CHANCE = 0.5
TEASE_FALLBACKS = [
    "{name}, ну вот, доигрался 😏 модерация не дремлет",
    "{name}, отдохни немного, подумай о вечном 🧘",
    "минус один шумный, {name}, без обид 🤐",
    "{name}, правила они такие, для всех 😅",
]
_last_tease: dict[int, float] = {}
_last_greet: dict[int, float] = {}
_greets: set[int] = set()     # чаты, где здоровается модератор
_client: httpx.AsyncClient | None = None
_guard_bot = {"username": "", "checked": 0.0}


async def init() -> None:
    await db.conn().executescript(SCHEMA)
    await db.conn().commit()
    async with db.conn().execute("SELECT chat_id FROM guard_chats WHERE greets = 1") as cur:
        _greets.update(r[0] for r in await cur.fetchall())
    from bot import textutil
    async with db.conn().execute("SELECT user_id, head, body, tail FROM guard_nicks WHERE body != ''") as cur:
        textutil.GUARD_NICK.update({r[0]: (r[1], r[2], r[3]) for r in await cur.fetchall()})


def guard_greets(chat_id: int) -> bool:
    """В чате приветствует модератор: Бакси на вход сам не здоровается, ждёт событие join."""
    return chat_id in _greets


def enabled() -> bool:
    """Связь с модератором включена: есть общий ключ."""
    return bool(config.BAXI_API_KEY)


def now() -> int:
    return int(time.time())


# ---------- события от модератора ----------

def parse_event(data: dict) -> dict:
    """Проверка тела POST /v1/events. ValueError: кривое событие."""
    if not isinstance(data, dict):
        raise ValueError("body")
    kind = str(data.get("type") or "")
    if kind not in EVENT_TYPES:
        raise ValueError("type")

    def num(key: str, default: int = 0) -> int:
        value = data.get(key, default)
        if isinstance(value, bool) or value is None:
            return default
        return int(value)
    ev = {"type": kind, "chat_id": num("chat_id"), "user_id": num("user_id"), "by_id": num("by_id"),
          "until": num("until"), "reason": str(data.get("reason") or "")[:300], "warns": num("warns", -1),
          "warn_limit": num("warn_limit", 0), "ts": num("ts") or now(),
          "name": str(data.get("name") or "")[:64], "on": bool(data.get("on")),
          "head": str(data.get("head") or "")[:600], "body": str(data.get("body") or "")[:600],
          "tail": str(data.get("tail") or "")[:600], "plain": str(data.get("plain") or "")[:64]}
    need_chat = kind != "nick"
    need_user = kind != "greet_mode"
    if (need_chat and not ev["chat_id"]) or (need_user and not ev["user_id"]):
        raise ValueError("ids")
    return ev


async def apply_event(ev: dict) -> None:
    """Запомнить событие и обновить состояние человека."""
    c = db.conn()
    chat_id, user_id, kind = ev["chat_id"], ev["user_id"], ev["type"]
    await c.execute("INSERT INTO guard_events (chat_id, user_id, by_id, type, until, reason, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (chat_id, user_id, ev["by_id"], kind, ev["until"], ev["reason"], ev["ts"]))
    await c.execute("INSERT OR IGNORE INTO guard_state (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    fields: dict = {"updated": now()}
    if ev["warns"] >= 0 and kind in ("warn", "unwarn", "mute", "ban"):
        fields["warns"] = ev["warns"]
    if ev["warn_limit"] > 0:
        fields["warn_limit"] = ev["warn_limit"]
    if kind == "mute":
        fields["muted_until"] = ev["until"] or -1
    elif kind == "unmute":
        fields["muted_until"] = 0
    elif kind == "ban":
        fields["banned_until"] = ev["until"] or -1
    elif kind == "unban":
        fields["banned_until"] = 0
    sets = ", ".join(f"{k} = ?" for k in fields)
    await c.execute(f"UPDATE guard_state SET {sets} WHERE chat_id = ? AND user_id = ?",
                    (*fields.values(), chat_id, user_id))
    await c.commit()


def _active(until: int) -> bool:
    return until == -1 or until > now()


async def state(chat_id: int, user_id: int) -> dict | None:
    async with db.conn().execute("SELECT * FROM guard_state WHERE chat_id = ? AND user_id = ?",
                                 (chat_id, user_id)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def is_blocked(chat_id: int, user_id: int) -> bool:
    """Замучен или забанен модератором: Бакси ему не отвечает и не зовёт в игры."""
    st = await state(chat_id, user_id)
    return bool(st and (_active(st["muted_until"]) or _active(st["banned_until"])))


async def blocked_ids(chat_id: int) -> set[int]:
    t = now()
    async with db.conn().execute(
            "SELECT user_id FROM guard_state WHERE chat_id = ? AND (muted_until = -1 OR muted_until > ? "
            "OR banned_until = -1 OR banned_until > ?)", (chat_id, t, t)) as cur:
        return {r[0] for r in await cur.fetchall()}


async def warns_line(chat_id: int, user_id: int) -> str:
    """Строка для /me. Пусто, если предупреждений нет."""
    st = await state(chat_id, user_id)
    if not st or st["warns"] <= 0:
        return ""
    return f"⚠️ предупреждения {st['warns']}/{st['warn_limit']}"


HISTORY_TYPES = ("warn", "mute", "ban", "kick")
HISTORY_ICONS = {"warn": "⚠️ предупреждение", "mute": "🔇 мут", "ban": "⛔ бан", "kick": "👢 кик"}


def _left(until: int) -> str:
    """Срок наказания коротко: 'до 18:30', 'до 21.11', 'навсегда'."""
    if until == -1 or until == 0:
        return "навсегда"
    import datetime
    dt = datetime.datetime.fromtimestamp(until, config.TZ)
    today = datetime.datetime.now(config.TZ).date()
    return "до " + (dt.strftime("%H:%M") if dt.date() == today else dt.strftime("%d.%m %H:%M"))


async def history(chat_id: int, user_id: int, limit: int = 5) -> list[dict]:
    async with db.conn().execute(
            "SELECT type, until, reason, ts FROM guard_events WHERE chat_id = ? AND user_id = ? AND type IN "
            "('warn', 'mute', 'ban', 'kick') ORDER BY ts DESC, id DESC LIMIT ?", (chat_id, user_id, limit)) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def card_lines(chat_id: int, user_id: int) -> tuple[str, list[str]]:
    """Для /me: (строка состояния, история с причинами). Состояние: предупреждения и текущий мут или бан."""
    from bot.textutil import esc
    import datetime
    st = await state(chat_id, user_id)
    parts = []
    if st and st["warns"] > 0:
        parts.append(f"предупреждения {st['warns']}/{st['warn_limit']}")
    if st and _active(st["banned_until"]):
        parts.append(f"бан {_left(st['banned_until'])}")
    elif st and _active(st["muted_until"]):
        parts.append(f"мут {_left(st['muted_until'])}")
    items = await history(chat_id, user_id)
    lines = []
    for h in items:
        when = datetime.datetime.fromtimestamp(h["ts"], config.TZ).strftime("%d.%m")
        line = f"{when} {HISTORY_ICONS[h['type']]}"
        if h["reason"]:
            line += f": {esc(h['reason'][:60])}"
        lines.append(line)
    if parts:
        status = "🛡 " + " · ".join(parts)
    elif items:
        status = "🛡 сейчас чисто"
    else:
        status = "🛡 нарушений нет"
    return status, lines


async def day_counts(chat_id: int, since: float) -> dict[str, int]:
    async with db.conn().execute("SELECT type, COUNT(*) FROM guard_events WHERE chat_id = ? AND ts >= ? "
                                 "GROUP BY type", (chat_id, int(since))) as cur:
        return {r[0]: r[1] for r in await cur.fetchall()}


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


SUMMARY_FORMS = [("mute", ("мут", "мута", "мутов")), ("warn", ("предупреждение", "предупреждения", "предупреждений")),
                 ("ban", ("бан", "бана", "банов")), ("kick", ("кик", "кика", "киков")),
                 ("spam", ("спам удалён", "спама удалено", "спама удалено"))]


def summary_line(counts: dict[str, int]) -> str:
    """'🛡 За день: 2 мута, 3 предупреждения'. Пусто, если наказаний не было."""
    parts = [f"{counts[k]} {_plural(counts[k], *forms)}" for k, forms in SUMMARY_FORMS if counts.get(k)]
    return ("🛡 <b>За день:</b> " + ", ".join(parts)) if parts else ""


async def cleanup() -> None:
    await db.conn().execute("DELETE FROM guard_events WHERE ts < ?", (now() - KEEP_DAYS * 86400,))
    await db.conn().execute("DELETE FROM guard_state WHERE warns = 0 AND muted_until = 0 AND banned_until = 0 "
                            "AND updated < ?", (now() - KEEP_DAYS * 86400,))
    await db.conn().commit()


# ---------- что делает Бакси после события ----------

async def on_punished(bot, chat_id: int, user_id: int, kind: str) -> None:
    """Бан, мут или кик: убрать человека из текущих игр и списков."""
    from bot.economy import service
    try:
        d = await service.cancel_duel_of(chat_id, user_id)
        if d is not None:
            from bot.services.out import say
            await say(bot, chat_id, "🎲 игра в кости отменена: одного из игроков убрала модерация"
                      + (", ставки вернул" if d.accepted else ""))
    except Exception:
        log.exception("Не отменил кости после наказания")
    if kind in ("ban", "kick"):
        await db.call_remove(chat_id, user_id)


async def maybe_tease(bot, ev: dict) -> None:
    """Подколка в характере Бакси, если админ включил её в «🛡 Модерация». Не чаще раза в 10 минут."""
    if ev["type"] not in ("warn", "mute", "ban"):
        return
    chat = await db.get_chat(ev["chat_id"])
    if not chat or not chat["guard_tease"] or not chat["active"] or not chat["approved"]:
        return
    t = time.time()
    if t - _last_tease.get(ev["chat_id"], 0) < TEASE_COOLDOWN or random.random() > TEASE_CHANCE:
        return
    _last_tease[ev["chat_id"]] = t
    users = await db.users_by_ids(ev["chat_id"], [ev["user_id"]])
    name = users[0]["name"] if users else "кто-то"
    what = {"warn": "получил предупреждение", "mute": "получил мут", "ban": "получил бан"}[ev["type"]]
    why = f" (причина: {ev['reason']})" if ev["reason"] else ""
    situation = (f"Модератор чата только что выдал: {name} {what}{why}. Подколи это одной короткой фразой в своём "
                 f"характере, по-дружески. Без оскорблений, никаких шуток про национальность и религию. "
                 f"Не говори, что ты модератор, ты просто участник, который это заметил.")
    from bot import ai
    from bot.services import talk
    ai.CURRENT_CHAT.set(chat)   # бесплатный чат: нейросети нет, будет заготовка
    fallbacks = [f.format(name=name) for f in TEASE_FALLBACKS]
    try:
        await talk.in_character(bot, ev["chat_id"], situation, fallbacks)
    except Exception:
        log.exception("Подколка не отправилась")


async def on_signal(bot, ev: dict) -> None:
    """join, greet_mode, nick."""
    c = db.conn()
    if ev["type"] == "greet_mode":
        await c.execute("INSERT INTO guard_chats (chat_id, greets, updated) VALUES (?, ?, ?) ON CONFLICT (chat_id) "
                        "DO UPDATE SET greets = excluded.greets, updated = excluded.updated",
                        (ev["chat_id"], int(ev["on"]), now()))
        await c.commit()
        (_greets.add if ev["on"] else _greets.discard)(ev["chat_id"])
    elif ev["type"] == "nick":
        from bot import textutil
        await c.execute("INSERT INTO guard_nicks (user_id, head, body, tail, plain, updated) VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (user_id) DO UPDATE SET head = excluded.head, body = excluded.body, "
                        "tail = excluded.tail, plain = excluded.plain, updated = excluded.updated",
                        (ev["user_id"], ev["head"], ev["body"], ev["tail"], ev["plain"], now()))
        await c.commit()
        if ev["body"]:
            textutil.GUARD_NICK[ev["user_id"]] = (ev["head"], ev["body"], ev["tail"])
        else:
            textutil.GUARD_NICK.pop(ev["user_id"], None)
    elif ev["type"] == "join":
        await greet_after_guard(bot, ev)


async def greet_after_guard(bot, ev: dict) -> None:
    """Модератор поприветствовал новичка: Бакси добавляет свою фразу, если в чате включено «здороваться»."""
    chat = await db.get_chat(ev["chat_id"])
    if not chat or not chat["active"] or not chat["approved"] or not chat["greet"]:
        return
    t = time.time()
    if t - _last_greet.get(ev["chat_id"], 0) < GREET_COOLDOWN:
        return
    _last_greet[ev["chat_id"]] = t
    from bot import ai
    from bot.services import talk
    ai.CURRENT_CHAT.set(chat)
    try:
        async with talk.chat_lock(ev["chat_id"]):
            await talk.greet(bot, chat, ev["user_id"], ev["name"] or "новичок")
    except Exception:
        log.exception("Не поздоровался после модератора в чате %s", ev["chat_id"])


async def spend_coins(user_id: int, amount: int, ref: str, reason: str) -> dict:
    """Списать монеты по просьбе модератора. Один ref списывается один раз (повтор запроса безопасен)."""
    from bot.economy import store
    c = db.conn()
    cur = await c.execute("INSERT OR IGNORE INTO guard_spends (ref, user_id, amount, reason, ts) VALUES (?, ?, ?, ?, ?)",
                          (ref, user_id, amount, reason[:100], now()))
    await c.commit()
    if cur.rowcount == 0:
        return {"ok": True, "repeat": True, "coins": (await store.wallet(user_id))["coins"]}
    if not await store.spend(user_id, amount):
        await c.execute("DELETE FROM guard_spends WHERE ref = ?", (ref,))
        await c.commit()
        return {"ok": False, "error": "not_enough", "coins": (await store.wallet(user_id))["coins"]}
    return {"ok": True, "coins": (await store.wallet(user_id))["coins"]}


async def handle(bot, ev: dict) -> None:
    """Всё по событию: запомнить, убрать из игр, подколоть."""
    if ev["type"] in SIGNALS:
        await on_signal(bot, ev)
        return
    await apply_event(ev)
    if ev["type"] in PUNISH:
        await on_punished(bot, ev["chat_id"], ev["user_id"], ev["type"])
    await maybe_tease(bot, ev)


# ---------- ники для модератора и сайта ----------

def plain_nick(text: str) -> str:
    """Простая версия ника для поиска, сортировки и упоминаний: без шрифтов и украшений.
    NFKC превращает «𝐁𝐚𝐤𝐬𝐢» и «Ｂａｋｓｉ» в обычное «Baksi»."""
    s = unicodedata.normalize("NFKC", text or "")
    s = "".join(ch for ch in s if ch.isalnum() or ch in " _-.")
    return " ".join(s.split())[:64]


async def nick_info(user_id: int) -> dict:
    """Как показывать человека: красивый ник (если куплен), простой ник и запасное имя из чатов."""
    from bot.services import stars
    async with db.conn().execute("SELECT name, username FROM users WHERE user_id = ? ORDER BY last_seen DESC LIMIT 1",
                                 (user_id,)) as cur:
        row = await cur.fetchone()
    name, username = (row["name"], row["username"]) if row else ("", "")
    perks = await db.get_perks(user_id)
    has = await stars.has_look(user_id)
    nick = (perks["nick"] if perks and has else "") or ""
    emoji_id = (perks["emoji_id"] if perks and has else "") or ""
    emoji = (perks["emoji_alt"] if perks and has else "") or ""
    return {"user_id": user_id, "name": name, "username": username, "nick": nick,
            "nick_plain": plain_nick(nick or name), "emoji_id": emoji_id, "emoji": emoji, "has_nick": bool(nick)}


# ---------- запросы к модератору (для экрана «🛡 Модерация») ----------

def _guard_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=config.GUARD_API_URL, timeout=3.0,
                                    headers={"X-Key": config.BAXI_API_KEY})
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def guard_get(path: str) -> dict | None:
    """GET к модератору. None: не настроен или не отвечает (тогда Бакси просто не показывает его данные)."""
    if not (enabled() and config.GUARD_API_URL):
        return None
    try:
        resp = await _guard_client().get(path)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


async def guard_overview(chat_id: int) -> dict | None:
    """Всё для экрана «🛡 Модерация»: пинг, защиты, наказания за сутки и за неделю."""
    ping = await guard_get("/v1/ping")
    if ping is None:
        return None
    return {"ping": ping,
            "settings": await guard_get(f"/v1/chat/{chat_id}/settings") or {"known": False},
            "day": await guard_get(f"/v1/chat/{chat_id}/stats?days=1") or {},
            "week": await guard_get(f"/v1/chat/{chat_id}/stats?days=7") or {}}
