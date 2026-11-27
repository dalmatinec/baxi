"""Погода в любом городе: «бакси погода алматы», «погода москва», /weather астана. Без нейросети и без ключей.

Данные: Open-Meteo (геокодер, прогноз, качество воздуха), бесплатно и без регистрации.
Если Open-Meteo не ответил, запасной источник wttr.in (без качества воздуха).
Ответы кешируются на 15 минут на город, геокодер навсегда (в памяти), чтобы не упираться в лимиты."""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from bot import config
from bot.textutil import esc

log = logging.getLogger(__name__)

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WTTR_URL = "https://wttr.in/{q}"
CACHE_SEC = 900

# код погоды WMO → эмодзи и описание
WMO = {
    0: ("☀️", "Ясно"), 1: ("🌤", "Почти ясно"), 2: ("⛅", "Переменная облачность"), 3: ("☁️", "Пасмурно"),
    45: ("🌫", "Туман"), 48: ("🌫", "Туман с изморозью"),
    51: ("🌦", "Лёгкая морось"), 53: ("🌦", "Морось"), 55: ("🌧", "Сильная морось"),
    56: ("🌧", "Ледяная морось"), 57: ("🌧", "Ледяная морось"),
    61: ("🌦", "Небольшой дождь"), 63: ("🌧", "Дождь"), 65: ("🌧", "Сильный дождь"),
    66: ("🌧", "Ледяной дождь"), 67: ("🌧", "Ледяной дождь"),
    71: ("🌨", "Небольшой снег"), 73: ("🌨", "Снег"), 75: ("❄️", "Сильный снег"), 77: ("🌨", "Снежная крупа"),
    80: ("🌦", "Ливень"), 81: ("🌧", "Ливень"), 82: ("⛈", "Сильный ливень"),
    85: ("🌨", "Снегопад"), 86: ("❄️", "Сильный снегопад"),
    95: ("⛈", "Гроза"), 96: ("⛈", "Гроза с градом"), 99: ("⛈", "Гроза с градом"),
}
# запасной источник wttr.in: свои коды → ближайший WMO
WTTR_TO_WMO = {113: 0, 116: 2, 119: 3, 122: 3, 143: 45, 248: 45, 260: 45, 176: 80, 263: 51, 266: 53, 281: 56,
               284: 57, 293: 61, 296: 61, 299: 63, 302: 63, 305: 65, 308: 65, 311: 66, 314: 67, 353: 80,
               356: 81, 359: 82, 179: 71, 182: 77, 185: 56, 227: 73, 230: 75, 317: 77, 320: 73, 323: 71,
               326: 71, 329: 73, 332: 73, 335: 75, 338: 75, 350: 77, 362: 85, 365: 85, 368: 85, 371: 86,
               374: 77, 377: 77, 200: 95, 386: 95, 389: 95, 392: 96, 395: 96}
WIND = ["северный", "северо-восточный", "восточный", "юго-восточный", "южный", "юго-западный", "западный",
        "северо-западный"]
DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря"]

# Частые города без обращения к геокодеру: имя, страна, широта, долгота, часовой пояс.
_C = {
    "алматы": ("Алматы", "Казахстан", 43.2525, 76.9115, "Asia/Almaty"),
    "астана": ("Астана", "Казахстан", 51.1801, 71.4460, "Asia/Almaty"),
    "шымкент": ("Шымкент", "Казахстан", 42.3000, 69.6000, "Asia/Almaty"),
    "караганда": ("Караганда", "Казахстан", 49.8047, 73.1094, "Asia/Almaty"),
    "актобе": ("Актобе", "Казахстан", 50.2797, 57.2072, "Asia/Aqtobe"),
    "тараз": ("Тараз", "Казахстан", 42.9000, 71.3667, "Asia/Almaty"),
    "павлодар": ("Павлодар", "Казахстан", 52.2873, 76.9674, "Asia/Almaty"),
    "усть-каменогорск": ("Усть-Каменогорск", "Казахстан", 49.9481, 82.6279, "Asia/Almaty"),
    "семей": ("Семей", "Казахстан", 50.4111, 80.2275, "Asia/Almaty"),
    "атырау": ("Атырау", "Казахстан", 47.1167, 51.8833, "Asia/Atyrau"),
    "актау": ("Актау", "Казахстан", 43.6500, 51.2000, "Asia/Aqtau"),
    "костанай": ("Костанай", "Казахстан", 53.2144, 63.6246, "Asia/Qostanay"),
    "кызылорда": ("Кызылорда", "Казахстан", 44.8528, 65.5092, "Asia/Qyzylorda"),
    "уральск": ("Уральск", "Казахстан", 51.2333, 51.3667, "Asia/Oral"),
    "петропавловск": ("Петропавловск", "Казахстан", 54.8667, 69.1500, "Asia/Almaty"),
    "туркестан": ("Туркестан", "Казахстан", 43.2973, 68.2518, "Asia/Almaty"),
    "талдыкорган": ("Талдыкорган", "Казахстан", 45.0156, 78.3739, "Asia/Almaty"),
    "кокшетау": ("Кокшетау", "Казахстан", 53.2833, 69.4000, "Asia/Almaty"),
    "экибастуз": ("Экибастуз", "Казахстан", 51.7298, 75.3266, "Asia/Almaty"),
    "конаев": ("Конаев", "Казахстан", 43.8667, 77.0667, "Asia/Almaty"),
    "москва": ("Москва", "Россия", 55.7558, 37.6173, "Europe/Moscow"),
    "санкт-петербург": ("Санкт-Петербург", "Россия", 59.9386, 30.3141, "Europe/Moscow"),
    "новосибирск": ("Новосибирск", "Россия", 55.0084, 82.9357, "Asia/Novosibirsk"),
    "екатеринбург": ("Екатеринбург", "Россия", 56.8389, 60.6057, "Asia/Yekaterinburg"),
    "казань": ("Казань", "Россия", 55.7887, 49.1221, "Europe/Moscow"),
    "омск": ("Омск", "Россия", 54.9885, 73.3242, "Asia/Omsk"),
    "бишкек": ("Бишкек", "Кыргызстан", 42.8746, 74.5698, "Asia/Bishkek"),
    "ташкент": ("Ташкент", "Узбекистан", 41.2995, 69.2401, "Asia/Tashkent"),
    "самарканд": ("Самарканд", "Узбекистан", 39.6542, 66.9597, "Asia/Samarkand"),
    "душанбе": ("Душанбе", "Таджикистан", 38.5598, 68.7870, "Asia/Dushanbe"),
    "баку": ("Баку", "Азербайджан", 40.4093, 49.8671, "Asia/Baku"),
    "тбилиси": ("Тбилиси", "Грузия", 41.7151, 44.8271, "Asia/Tbilisi"),
    "ереван": ("Ереван", "Армения", 40.1792, 44.4991, "Asia/Yerevan"),
    "минск": ("Минск", "Беларусь", 53.9006, 27.5590, "Europe/Minsk"),
    "киев": ("Киев", "Украина", 50.4501, 30.5234, "Europe/Kyiv"),
    "дубай": ("Дубай", "ОАЭ", 25.2048, 55.2708, "Asia/Dubai"),
    "стамбул": ("Стамбул", "Турция", 41.0082, 28.9784, "Europe/Istanbul"),
    "анталья": ("Анталья", "Турция", 36.8969, 30.7133, "Europe/Istanbul"),
    "пекин": ("Пекин", "Китай", 39.9042, 116.4074, "Asia/Shanghai"),
    "урумчи": ("Урумчи", "Китай", 43.8256, 87.6168, "Asia/Shanghai"),
    "сеул": ("Сеул", "Южная Корея", 37.5665, 126.9780, "Asia/Seoul"),
    "токио": ("Токио", "Япония", 35.6762, 139.6503, "Asia/Tokyo"),
    "бангкок": ("Бангкок", "Таиланд", 13.7563, 100.5018, "Asia/Bangkok"),
    "лондон": ("Лондон", "Великобритания", 51.5074, -0.1278, "Europe/London"),
    "париж": ("Париж", "Франция", 48.8566, 2.3522, "Europe/Paris"),
    "берлин": ("Берлин", "Германия", 52.5200, 13.4050, "Europe/Berlin"),
    "нью-йорк": ("Нью-Йорк", "США", 40.7128, -74.0060, "America/New_York"),
    # куда летают отдыхать
    "пхукет": ("Пхукет", "Таиланд", 7.8804, 98.3923, "Asia/Bangkok"),
    "паттайя": ("Паттайя", "Таиланд", 12.9236, 100.8825, "Asia/Bangkok"),
    "самуи": ("Самуи", "Таиланд", 9.5120, 100.0136, "Asia/Bangkok"),
    "бали": ("Бали", "Индонезия", -8.6705, 115.2126, "Asia/Makassar"),
    "нячанг": ("Нячанг", "Вьетнам", 12.2388, 109.1967, "Asia/Ho_Chi_Minh"),
    "фукуок": ("Фукуок", "Вьетнам", 10.2899, 103.9840, "Asia/Ho_Chi_Minh"),
    "гоа": ("Гоа", "Индия", 15.4909, 73.8278, "Asia/Kolkata"),
    "мальдивы": ("Мальдивы", "Мальдивы", 4.1755, 73.5093, "Indian/Maldives"),
    "шри-ланка": ("Шри-Ланка", "Шри-Ланка", 6.9271, 79.8612, "Asia/Colombo"),
    "шарм-эль-шейх": ("Шарм-эль-Шейх", "Египет", 27.9158, 34.3300, "Africa/Cairo"),
    "хургада": ("Хургада", "Египет", 27.2579, 33.8116, "Africa/Cairo"),
    "кемер": ("Кемер", "Турция", 36.5978, 30.5601, "Europe/Istanbul"),
    "аланья": ("Аланья", "Турция", 36.5444, 31.9954, "Europe/Istanbul"),
    "абу-даби": ("Абу-Даби", "ОАЭ", 24.4539, 54.3773, "Asia/Dubai"),
    "сочи": ("Сочи", "Россия", 43.6028, 39.7342, "Europe/Moscow"),
    "иссык-куль": ("Иссык-Куль (Чолпон-Ата)", "Кыргызстан", 42.6497, 77.0819, "Asia/Bishkek"),
    "боровое": ("Боровое", "Казахстан", 53.0833, 70.3000, "Asia/Almaty"),
}
_ALIAS = {"паттайе": "паттайя", "мальдивах": "мальдивы", "шри ланка": "шри-ланка", "шри-ланке": "шри-ланка",
          "шарме": "шарм-эль-шейх", "шарм": "шарм-эль-шейх", "египте": "хургада", "египет": "хургада",
          "тайланд": "пхукет", "таиланд": "пхукет", "тае": "пхукет", "вьетнам": "нячанг", "вьетнаме": "нячанг",
          "турция": "анталья", "турции": "анталья", "чолпон-ата": "иссык-куль", "иссык куль": "иссык-куль",
          "борово": "боровое", "бурабай": "боровое", "абу даби": "абу-даби", "эмираты": "дубай", "оаэ": "дубай",
          "алмате": "алматы", "алмата": "алматы", "алма-ата": "алматы", "нур-султан": "астана",
          "нурсултан": "астана", "караганды": "караганда", "уральске": "уральск", "оскемен": "усть-каменогорск",
          "усть-каменогорске": "усть-каменогорск", "питер": "санкт-петербург", "питере": "санкт-петербург",
          "спб": "санкт-петербург", "петербург": "санкт-петербург", "петербурге": "санкт-петербург",
          "мск": "москва", "дубаи": "дубай", "нью-йорке": "нью-йорк", "нью йорк": "нью-йорк",
          "капчагай": "конаев", "семипалатинск": "семей"}
_geo: dict[str, dict | None] = {}
_cache: dict[tuple, tuple[float, dict]] = {}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10, headers={"User-Agent": "baxi-bot"})
    return _client


def temp(t: float) -> str:
    """+4°, −3°, 0° (минус настоящий, не дефис)."""
    v = round(t)
    return "0°" if v == 0 else f"+{v}°" if v > 0 else f"−{abs(v)}°"


def wind_dir(deg: float) -> str:
    return WIND[int((deg % 360 + 22.5) // 45) % 8]


def aqi_text(aqi: float | None) -> str:
    if aqi is None:
        return ""
    a = round(aqi)
    word = ("хороший" if a <= 50 else "умеренный" if a <= 100 else "вредный для чувствительных" if a <= 150
            else "вредный" if a <= 200 else "очень вредный" if a <= 300 else "опасный")
    return f"{word} (AQI {a})"


def variants(city: str) -> list[str]:
    """«в Москве», «в Дубае», «в Шымкенте», «в Казани»: пробуем вернуть именительный падеж."""
    c = " ".join(city.lower().replace("ё", "е").split())
    out = [c]
    if len(c) > 3 and c[-1] in "еиуюы":
        base = c[:-1]
        out += [base, base + "а", base + "й", base + "ь", base + "ы", base + "я"]
    return list(dict.fromkeys(out))


def _place(name: str, country: str, lat: float, lon: float, tz: str) -> dict:
    return {"name": name, "country": country, "lat": lat, "lon": lon, "tz": tz}


async def _geo_api(name: str) -> dict | None:
    """Геокодер Open-Meteo. Исключение при сбое сети, None если город не найден."""
    resp = await _http().get(GEO_URL, params={"name": name, "count": 1, "language": "ru"})
    if resp.status_code != 200:
        raise httpx.HTTPError(f"geo {resp.status_code}")
    res = resp.json().get("results") or []
    if not res:
        return None
    r = res[0]
    return _place(r.get("name") or name, r.get("country") or "", r["latitude"], r["longitude"],
                  r.get("timezone") or "UTC")


async def _geo_wttr(name: str) -> dict | None:
    """Запасной геокодер: wttr.in по названию. Часовой пояс приблизительно по долготе."""
    resp = await _http().get(WTTR_URL.format(q=name), params={"format": "j1"})
    a = resp.json()["nearest_area"][0]
    lat, lon = float(a["latitude"]), float(a["longitude"])
    hours = round(lon / 15)
    tz = f"Etc/GMT{'-' if hours >= 0 else '+'}{abs(hours)}"   # у Etc/GMT знак наоборот
    return _place(name[:1].upper() + name[1:], a["country"][0]["value"] if a.get("country") else "", lat, lon, tz)


async def geocode(city: str) -> dict | None:
    """Город → {name, country, lat, lon, tz}: сначала свой список частых городов, потом Open-Meteo, потом wttr.in."""
    key = " ".join(city.strip().lower().split())
    if key in _geo:
        return _geo[key]
    tries = variants(key)
    for v in tries:
        v = _ALIAS.get(v, v)
        if v in _C:
            _geo[key] = _place(*_C[v])
            return _geo[key]
    found, net_ok = None, False
    for v in tries[:4]:
        try:
            found = await _geo_api(v)
            net_ok = True
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.info("Геокодер не ответил для %r: %s", v, exc)
            break
        if found:
            break
    if not found and not net_ok:
        try:
            found = await _geo_wttr(key)
            net_ok = True
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            log.info("Запасной геокодер не ответил для %r: %s", key, exc)
    if net_ok:
        _geo[key] = found   # «не нашли» тоже запоминаем, а сбой сети нет
    return found


async def _open_meteo(place: dict) -> dict | None:
    params = {"latitude": place["lat"], "longitude": place["lon"], "timezone": place["tz"], "forecast_days": 3,
              "wind_speed_unit": "ms",
              "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                         "wind_speed_10m,wind_direction_10m",
              "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
              "hourly": "precipitation_probability"}
    resp = await _http().get(FORECAST_URL, params=params)
    data = resp.json()
    if resp.status_code != 200 or data.get("error"):
        raise ValueError(data.get("reason") or resp.status_code)
    cur, daily, hourly = data["current"], data["daily"], data["hourly"]
    now = datetime.fromisoformat(cur["time"])
    probs = [p or 0 for t, p in zip(hourly["time"], hourly["precipitation_probability"], strict=False)
             if now <= datetime.fromisoformat(t) < now + timedelta(hours=6)]
    out = {"t": cur["temperature_2m"], "feels": cur["apparent_temperature"], "hum": cur["relative_humidity_2m"],
           "code": cur["weather_code"], "wind": cur["wind_speed_10m"], "wdeg": cur["wind_direction_10m"],
           "rain": max(probs) if probs else None,
           "sunrise": daily["sunrise"][0][-5:], "sunset": daily["sunset"][0][-5:],
           "days": [(daily["weather_code"][i], daily["temperature_2m_min"][i], daily["temperature_2m_max"][i])
                    for i in range(min(3, len(daily["time"])))],
           "aqi": None}
    try:
        air = await _http().get(AIR_URL, params={"latitude": place["lat"], "longitude": place["lon"],
                                                 "current": "us_aqi"})
        out["aqi"] = air.json()["current"]["us_aqi"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    return out


def _ampm(s: str) -> str:
    """07:57 AM → 07:57, 05:21 PM → 17:21."""
    try:
        return datetime.strptime(s.strip(), "%I:%M %p").strftime("%H:%M")
    except ValueError:
        return s


async def _wttr(place: dict) -> dict | None:
    resp = await _http().get(WTTR_URL.format(q=f"{place['lat']},{place['lon']}"), params={"format": "j1"})
    data = resp.json()
    c = data["current_condition"][0]
    days = [(WTTR_TO_WMO.get(int(w["hourly"][4]["weatherCode"]), 3), float(w["mintempC"]), float(w["maxtempC"]))
            for w in data["weather"][:3]]
    today = data["weather"][0]
    return {"t": float(c["temp_C"]), "feels": float(c["FeelsLikeC"]), "hum": float(c["humidity"]),
            "code": WTTR_TO_WMO.get(int(c["weatherCode"]), 3), "wind": float(c["windspeedKmph"]) / 3.6,
            "wdeg": float(c["winddirDegree"]),
            "rain": max(int(h["chanceofrain"]) for h in today["hourly"][:4]) if today.get("hourly") else None,
            "sunrise": _ampm(today["astronomy"][0]["sunrise"]), "sunset": _ampm(today["astronomy"][0]["sunset"]),
            "days": days, "aqi": None}


async def forecast(place: dict) -> dict | None:
    key = (round(place["lat"], 2), round(place["lon"], 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SEC:
        return hit[1]
    data = None
    for source in (_open_meteo, _wttr):
        try:
            data = await source(place)
            break
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            log.info("Погода: %s не ответил: %s", source.__name__, exc)
    if data:
        _cache[key] = (time.time(), data)
    return data


def _day(day: tuple | None) -> str:
    if not day:
        return "нет данных"
    code, lo, hi = day
    e, t = WMO.get(code, ("🌡", ""))
    return f"{e} {temp(lo)}…{temp(hi)}" + (f", {t.lower()}" if t else "")


async def card(place: dict, w: dict, now: datetime | None = None) -> str:
    """Карточка погоды (HTML) по шаблону, который владелец может поменять в админке (Тексты → Погода и курсы).
    Эмодзи в ней, как и везде, заменяются на премиум из эмодзи-пака бота."""
    from bot.services import texts
    now = now or datetime.now(ZoneInfo(place["tz"]))
    emoji, text = WMO.get(w["code"], ("🌡", ""))
    today = w["days"][0] if w["days"] else None
    return await texts.render(
        "wx_card", иконка=emoji,
        город=esc(place["name"]) + (f", {esc(place['country'])}" if place["country"] else ""),
        время=f"{now:%H:%M}", день=f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}",
        темп=temp(w["t"]), ощущается=temp(w["feels"]), погода=text or "нет данных",
        днём=temp(today[2]) if today else "?", ночью=temp(today[1]) if today else "?",
        ветер=f"{round(w['wind'])} м/с, {wind_dir(w['wdeg'])}", влажность=f"{round(w['hum'])}%",
        осадки=f"{round(w['rain'])}% в ближайшие 6 часов" if w.get("rain") is not None else "нет данных",
        воздух=aqi_text(w["aqi"]) if w.get("aqi") is not None else "нет данных",
        восход=w["sunrise"], закат=w["sunset"],
        завтра=_day(w["days"][1] if len(w["days"]) > 1 else None),
        послезавтра=_day(w["days"][2] if len(w["days"]) > 2 else None))


async def weather_html(city: str) -> str | None:
    """Готовая карточка. None, если город не нашёлся. Строка с ошибкой, если погода не ответила."""
    place = await geocode(city or config.WEATHER_CITY)
    if not place:
        return None
    w = await forecast(place)
    if not w:
        return "🌤 Погода сейчас не отвечает, попробуй через пару минут"
    return await card(place, w)


HELP = ("🌤 <b>Погода</b>\n\n"
        "Напиши в чат:\n"
        "• <b>погода</b>: погода в {city}\n"
        "• <b>погода москва</b>, <b>бакси погода в дубае</b>: в любом городе\n"
        "• /weather астана\n\n"
        "Покажу время, температуру, ветер, осадки, воздух, восход и закат и прогноз на два дня.")
