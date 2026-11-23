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
    ("talk", re.compile(r"можно\s+(болтать|говорить)|можешь\s+говорить|хватит\s+молчать|говори\s+снова|"
                        r"возвращайся|отмолчался", re.I)),
    ("quiet", re.compile(r"помолчи|замолчи|заткнись|не\s+мешай|потише|отдохни\s+час|тихо\s+будь|умолкни", re.I)),
    ("summary", re.compile(r"(что|чо|чё|че|шо)\s+(тут|здесь|там)?\s*(было|происходило|обсуждали|пропустил|случилось)|"
                           r"о\s+ч[её]м\s+(тут\s+|здесь\s+)?(говорили|болтали|речь|спорили)|выжимк|итоги\s+за|"
                           r"кратко\s+(что|о\s+ч[её]м)", re.I)),
    ("roast", re.compile(r"прожар|прожги|зажарь|обосри|разнеси\s+его|разнеси\s+её", re.I)),
    ("quiz", re.compile(r"викторин", re.I)),
    ("joke", re.compile(r"шутк|анекдот|рассмеши|пошути|прикол\s+расскажи|расскажи\s+прикол", re.I)),
]


_COMMANDS = [
    ("results", re.compile(r"^\s*(итоги|итоги дня|/results|/itogi)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("pair", re.compile(r"^\s*(пара|как вам пара|/pair)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("settings", re.compile(r"^\s*(настройки|настройки бота|/settings)(@\w+)?\s*[!?.]*\s*$", re.I)),
    ("summary", re.compile(r"^\s*(сводка|/summary)(@\w+)?(\s+за\s+.{1,20})?\s*[!?.]*\s*$", re.I)),
    ("quiet", re.compile(r"^\s*/quiet(@\w+)?\s*$", re.I)),
    ("talk", re.compile(r"^\s*/talk(@\w+)?\s*$", re.I)),
    ("stopcall", re.compile(r"^\s*(/stopcall|стоп\s+зазыв\w*|хватит\s+звать)(@\w+)?\s*[!.]*\s*$", re.I)),
    ("call", re.compile(r"^\s*(/call|зазывай|зазывала|зови\s+всех)(@\w+)?\s*[!.]*\s*$", re.I)),
    ("joke", re.compile(r"^\s*/joke(@\w+)?\s*$", re.I)),
    ("roast", re.compile(r"^\s*/roast(@\w+)?(\s+.{1,40})?\s*$", re.I)),
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


READ_MIN, READ_MAX = 2.0, 3.5   # человек сначала читает сообщение, секунды
CHARS_PER_SEC = 7.0             # и печатает с телефона примерно так
TOTAL_MIN, TOTAL_MAX = 4.0, 7.0  # весь ответ от прихода сообщения: не быстрее 4 и не дольше 7 секунд


def typing_delay(text: str) -> float:
    """Сколько в сумме должен занять ответ от прихода сообщения: прочитать + напечатать.
    Время, пока думала нейросеть, сюда входит, поэтому лишнего ожидания не бывает."""
    total = random.uniform(READ_MIN, READ_MAX) + len(text) / CHARS_PER_SEC
    return max(TOTAL_MIN + random.uniform(0, 1), min(total, TOTAL_MAX))
