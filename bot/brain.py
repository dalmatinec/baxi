"""Решения «отвечать или промолчать и чем отвечать». Чистая логика без Telegram,
поэтому покрыта тестами."""

import random
import re
from enum import Enum


class Act(Enum):
    NONE = "none"
    AI_REPLY = "ai_reply"   # к боту обратились: отвечает нейросеть
    AI_JUMP = "ai_jump"     # сам влез в разговор через нейросеть
    PHRASE = "phrase"       # сам влез: фраза, стикер или гифка из базы


_WORD = re.compile(r"[\wё]+", re.I)


def parse_aliases(bot_name: str, aliases: str) -> list[str]:
    """Имя бота и доп. имена через запятую: «Марат, маратик, мара» → ['марат', 'маратик', 'мара']."""
    items = [bot_name] + aliases.split(",")
    out = []
    for item in items:
        item = item.strip().lower().replace("ё", "е")
        if len(item) >= 2 and item not in out:
            out.append(item)
    return out


def mentions_name(text: str, aliases: list[str]) -> bool:
    """Есть ли в тексте имя бота, в том числе в другом падеже: марат, марату, маратик."""
    words = [w.lower().replace("ё", "е") for w in _WORD.findall(text or "")]
    joined = " ".join(words)
    for alias in aliases:
        if " " in alias:
            if f" {alias} " in f" {joined} ":
                return True
            continue
        for w in words:
            if w == alias:
                return True
            # окончания: «марат» → «марату», «марата», «маратик»; короткие имена только целиком
            if len(alias) >= 4 and w.startswith(alias) and len(w) - len(alias) <= 3:
                return True
    return False


def is_addressed(text: str, bot_username: str, aliases: list[str], reply_to_bot: bool) -> bool:
    if reply_to_bot:
        return True
    low = (text or "").lower()
    if bot_username and f"@{bot_username.lower()}" in low:
        return True
    return mentions_name(text, aliases)


def decide(addressed: bool, now: float, last_jump: float, cooldown: int,
           chance: float, ai_share: float, rnd: random.Random | None = None) -> Act:
    rnd = rnd or random
    if addressed:
        return Act.AI_REPLY
    if now - last_jump < cooldown:
        return Act.NONE
    if rnd.random() >= chance:
        return Act.NONE
    return Act.AI_JUMP if rnd.random() < ai_share else Act.PHRASE


class RateLimit:
    """Не больше limit обращений за window секунд от одного человека в одном чате."""

    def __init__(self, limit: int = 5, window: float = 60):
        self.limit, self.window = limit, window
        self._hits: dict[tuple[int, int], list[float]] = {}

    def allow(self, chat_id: int, user_id: int, now: float) -> bool:
        key = (chat_id, user_id)
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        ok = len(hits) < self.limit
        if ok:
            hits.append(now)
        self._hits[key] = hits
        if len(self._hits) > 5000:  # чистим старое, чтобы память не росла
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
        return ok


_INTENTS = [
    ("summary", re.compile(r"(что|чо|чё|че|шо)\s+(тут|здесь|там)?\s*(было|происходило|обсуждали|пропустил|случилось)|"
                           r"о\s+ч[её]м\s+(тут\s+|здесь\s+)?(говорили|болтали|речь|спорили)|выжимк|итоги\s+за|"
                           r"кратко\s+(что|о\s+ч[её]м)", re.I)),
    ("roast_full", re.compile(r"прожар\w*\s+(?:[\w@ё]+\s+)?по\s+полной|по\s+полной\s+прожар", re.I)),
    ("roast", re.compile(r"прожар|прожги|зажарь|обосри|разнеси\s+его|разнеси\s+её", re.I)),
    ("quiz", re.compile(r"викторин", re.I)),
    ("joke", re.compile(r"шутк|анекдот|рассмеши|пошути|прикол\s+расскажи|расскажи\s+прикол", re.I)),
]


_COMMANDS = [
    ("results", re.compile(r"^\s*(итоги|итоги дня|/results|/itogi)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("pair", re.compile(r"^\s*(пара|как вам пара|/pair)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("settings", re.compile(r"^\s*(настройки|настройки бота|/settings)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("shop", re.compile(r"^\s*(магазин|/shop)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("summary", re.compile(r"^\s*(сводка|/summary)(@\w+)?(\s+за\s+.{1,20})?\s*[!?.]*\s*$", re.I)),
]


def detect_command(text: str) -> str | None:
    """Команды без обращения: «итоги» (всем, раз в час), «пара» и «сводка» (только админам)."""
    for name, rx in _COMMANDS:
        if rx.match(text or ""):
            return name
    return None


def detect_intent(text: str) -> str | None:
    """Что просят у бота при обращении: выжимку, прожарку, викторину, шутку. Иначе просто болтовня."""
    for name, rx in _INTENTS:
        if rx.search(text or ""):
            return name
    return None


def pick_phrase_kind(rnd: random.Random | None = None) -> str:
    """Чем влезть без ИИ: чаще текстом, иногда стикером или гифкой."""
    x = (rnd or random).random()
    return "text" if x < 0.6 else "sticker" if x < 0.85 else "gif"


def typing_delay(text: str) -> float:
    """Сколько «печатать» перед отправкой, чтобы не отвечать мгновенно как робот."""
    return min(1.0 + len(text) / 25, 5.0)
