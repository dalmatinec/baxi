"""Номинации (болтун, самый смешной, матершинник) и разбор периода «за час / за день».
Чистая логика без Telegram и базы, покрыта тестами."""

import re
from dataclasses import dataclass, field

from bot.textutil import is_laugh, is_mat


@dataclass
class Person:
    user_id: int
    name: str
    msgs: int = 0
    mat: int = 0
    laughs: int = 0   # сколько раз ему ответили смехом
    reacts: int = 0   # сколько реакций собрали его сообщения

    @property
    def funny(self) -> int:
        return self.laughs + self.reacts

    @property
    def mat_pct(self) -> int:
        return round(self.mat * 100 / self.msgs) if self.msgs else 0


@dataclass
class Nominees:
    total: int = 0
    people: int = 0
    talker: Person | None = None
    funny: Person | None = None
    swearer: Person | None = None
    extra: dict = field(default_factory=dict)


def people_from_history(rows, reacts: dict[int, int], names: dict[int, str]) -> list[Person]:
    """rows: история (user_id, name, text, is_bot, reply_user_id). reacts: user_id → реакций."""
    by_id: dict[int, Person] = {}

    def get(uid: int, name: str) -> Person:
        if uid not in by_id:
            by_id[uid] = Person(uid, name)
        return by_id[uid]

    for r in rows:
        if r["is_bot"]:
            continue
        p = get(r["user_id"], r["name"])
        p.msgs += 1
        p.mat += is_mat(r["text"])
        to = r["reply_user_id"]
        if to and to != r["user_id"] and is_laugh(r["text"]):
            get(to, names.get(to, r["reply_name"] or "кто-то")).laughs += 1
    for uid, n in reacts.items():
        if uid in by_id or uid in names:
            get(uid, names.get(uid, "кто-то")).reacts += n
    return list(by_id.values())


def people_from_daily(rows, reacts: dict[int, int]) -> list[Person]:
    out = {r["user_id"]: Person(r["user_id"], r["name"], r["msgs"], r["mat"], r["laughs"]) for r in rows}
    for uid, n in reacts.items():
        if uid in out:
            out[uid].reacts += n
    return list(out.values())


def nominate(people: list[Person], min_msgs: int = 5) -> Nominees:
    talkers = [p for p in people if p.msgs > 0]
    n = Nominees(total=sum(p.msgs for p in talkers), people=len(talkers))
    if not talkers:
        return n
    n.talker = max(talkers, key=lambda p: (p.msgs, -p.user_id))
    funny = [p for p in people if p.funny > 0]
    if funny:
        n.funny = max(funny, key=lambda p: (p.funny, p.msgs))
    swearers = [p for p in talkers if p.msgs >= min_msgs and p.mat > 0]
    if swearers:
        n.swearer = max(swearers, key=lambda p: (p.mat_pct, p.mat))
    return n


_PERIOD = re.compile(r"за\s+(?:(\d+|пол|полтора|два|три)\s*)?(минут|мин|час|часа|часов|ч|сутки|день|дня)", re.I)
_WORDS = {"пол": 0.5, "полтора": 1.5, "два": 2, "три": 3}


def parse_period(text: str) -> tuple[int, str]:
    """«что было за 3 часа» → (10800, 'за 3 часа'). По умолчанию час, максимум сутки."""
    low = (text or "").lower()
    if "сегодня" in low or "за день" in low or "за сутки" in low:
        return 86400, "за сутки"
    m = _PERIOD.search(low)
    if not m:
        return 3600, "за час"
    raw, unit = m.group(1), m.group(2)
    num = float(_WORDS.get(raw, raw)) if raw else 1.0
    if unit.startswith("мин"):
        secs = num * 60
    elif unit in ("сутки", "день", "дня"):
        secs = num * 86400
    else:
        secs = num * 3600
    secs = int(min(max(secs, 600), 86400))
    return secs, _label(secs)


def _label(secs: int) -> str:
    if secs >= 86400:
        return "за сутки"
    if secs < 3600:
        return f"за {secs // 60} мин"
    hours = secs / 3600
    if hours == 1:
        return "за час"
    if hours == int(hours):
        h = int(hours)
        word = "час" if h % 10 == 1 and h % 100 != 11 else \
            "часа" if h % 10 in (2, 3, 4) and h % 100 not in (12, 13, 14) else "часов"
        return f"за {h} {word}"
    return f"за {hours:g} ч"
