"""Режим «меня обновляют»: владелец включает /maint, пока возится с ботом.

Пока режим включён:
  - нейросеть не тратится нигде (ai.PAUSED_UNTIL), сам бот в разговоры не влезает;
  - на прямые обращения отвечает прикольной фразой из списка ниже, без ИИ;
  - в одном чате не чаще раза в 45 секунд, одному человеку не чаще раза в 10 минут, чтобы не спамить;
  - игры, ранги, монеты и команды работают как обычно.
Режим хранится в базе и переживает перезапуски, сам выключается по таймеру (по умолчанию через 2 часа)."""

import random
import time

from bot import ai, db

DEFAULT_MIN = 120
PER_CHAT = 45
PER_USER = 600

PHRASES = [
    "меня щас обновляют, вернусь свежим как огурчик 🥒",
    "я на техосмотре, мне меняют масло в мозгах, скоро буду",
    "тихо, мне ставят новые извилины, подождите немного",
    "ушёл на прокачку, вернусь с новыми скиллами 💪",
    "создатель ковыряется у меня в голове, говорить пока не могу",
    "я на апдейте, как телефон ночью, не трогайте 🔌",
    "мне сейчас чинят болтливость, скоро вернусь ещё болтливее",
    "перезагружаюсь, если вернусь странным, это фича",
    "я в салоне красоты для ботов, скоро буду красивый",
    "обновляюсь, потерпите, вернусь умнее чем был (наверное)",
    "у меня технический перерыв, как в столовке, скоро открою",
    "меня разобрали на запчасти, собирают обратно, держитесь",
    "загружаюсь 47%... ладно, ещё немного 😅",
    "я на курсах повышения квалификации, скоро вернусь",
    "не до вас щас, мне мозги перепрошивают 🔧",
]

_until = 0.0
_chat_last: dict[int, float] = {}
_user_last: dict[int, float] = {}


def is_on() -> bool:
    return time.time() < _until


def until() -> float:
    return _until


def _apply(value: float) -> None:
    global _until
    _until = value
    ai.PAUSED_UNTIL = value


async def load() -> None:
    try:
        _apply(float(await db.kv_get("maint_until", "0") or 0))
    except ValueError:
        _apply(0)


async def turn_on(minutes: int = DEFAULT_MIN) -> float:
    value = time.time() + max(1, minutes) * 60
    await db.kv_set("maint_until", str(value))
    _apply(value)
    return value


async def turn_off() -> None:
    await db.kv_set("maint_until", "0")
    _apply(0)
    _chat_last.clear()
    _user_last.clear()


def pick(chat_id: int, user_id: int, now: float | None = None) -> str | None:
    """Фраза для ответа или None, если в этом чате или этому человеку уже недавно отвечали."""
    now = now or time.time()
    if now - _chat_last.get(chat_id, 0) < PER_CHAT or now - _user_last.get(user_id, 0) < PER_USER:
        return None
    _chat_last[chat_id] = now
    _user_last[user_id] = now
    return random.choice(PHRASES)
