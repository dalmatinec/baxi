"""Погода и курсы в чате и в личке: «погода», «погода москва», «бакси погода в дубае», /weather астана;
«курс», «курс доллара», «крипта», /rates."""

import re

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message

from bot import config
from bot.services import weather
from bot.services.out import say
from bot.textutil import esc

router = Router(name="weather")

_CMD = re.compile(r"^/(?:weather|pogoda)(?:@\w+)?(?:\s+(.+))?$", re.I)
_TEXT = re.compile(r"^(?:а\s+)?(?:(?P<name>[^\s,]+)[,\s]+)?(?:а\s+)?(?:какая|скажи|покажи|че\s+по|чё\s+по|как)?\s*"
                   r"погод[аеуы](?:\s+(?:в|во|на)\s+|\s+|$)(?P<city>.*)$", re.I)


def parse(text: str, bot_name: str = "") -> tuple[str, bool] | None:
    """(город, явно ли просили) или None. Явно: /weather или по имени бота. «погода X» без имени: только
    если X похож на город (до 4 слов), иначе это просто разговор про погоду."""
    t = (text or "").strip()
    if not t or len(t) > 60:
        return None
    m = _CMD.match(t)
    if m:
        return (m.group(1) or "").strip(" ?!.,"), True
    m = _TEXT.match(t)
    if not m:
        return None
    name = (m.group("name") or "").lower()
    if name in ("какая", "скажи", "покажи", "как", "а"):
        name = ""
    own = (bot_name or "").split()[0].lower() if bot_name else ""
    if name and name not in (own, "бакси", "бот"):
        return None
    city = m.group("city").strip(" ?!.,")
    if len(city.split()) > 4:
        return None
    return city, bool(name)


def _filter(message: Message, chat_row=None) -> dict | bool:
    got = parse(message.text or "", chat_row["bot_name"] if chat_row is not None else "")
    return {"city": got[0], "explicit": got[1]} if got else False


@router.message(F.text, _filter)
async def on_weather(message: Message, bot: Bot, city: str, explicit: bool) -> None:
    html = await weather.weather_html(city)
    if html is None:
        if not explicit and city:
            raise SkipHandler()   # «погода сегодня огонь»: это не запрос погоды, пусть ответит как обычно
        return await say(bot, message.chat.id, f"🌤 не нашёл город <b>{esc(city or config.WEATHER_CITY)}</b>, "
                                               "напиши по-другому, например: погода алматы", reply_to=message)
    await say(bot, message.chat.id, html, reply_to=message)


# ---------- курсы валют и крипты ----------

_RATES_CMD = re.compile(r"^/(?:rates|kurs|crypto)(?:@\w+)?$", re.I)
_RATES = re.compile(r"^(?:а\s+)?(?:(?P<name>[^\s,]+)[,\s]+)?(?:а\s+)?(?:какой\s+|скажи\s+|покажи\s+)?"
                    r"(?:курсы?(?:\s+(?:валют[ыа]?|доллара|долара|бакса|евро|рубля|юаня|тенге|крипты|крипта|"
                    r"биткоина|битка|usdt|тона|тон))?|крипта|крипту)\s*[?!.]*$", re.I)


def is_rates(text: str, bot_name: str = "") -> bool:
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if _RATES_CMD.match(t):
        return True
    m = _RATES.match(t)
    if not m:
        return False
    name = (m.group("name") or "").lower()
    own = (bot_name or "").split()[0].lower() if bot_name else ""
    return not name or name in (own, "бакси", "бот", "какой", "скажи", "покажи", "а")


def _rates_filter(message: Message, chat_row=None) -> bool:
    return is_rates(message.text or "", chat_row["bot_name"] if chat_row is not None else "")


@router.message(F.text, _rates_filter)
async def on_rates(message: Message, bot: Bot) -> None:
    from bot.services import rates
    await say(bot, message.chat.id, await rates.rates_html(), reply_to=message)
