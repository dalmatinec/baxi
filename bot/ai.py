"""Запросы к нейросети через API в формате OpenAI.
Следит за дневным лимитом трат: кончился лимит, функции возвращают None,
и бот отвечает фразами из базы."""

import asyncio
import json
import logging
from contextvars import ContextVar
import random
import re
import time

import httpx

from bot import config, db

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_slots = asyncio.Semaphore(3)  # не больше 3 запросов к ИИ одновременно


def enabled() -> bool:
    return bool(config.AI_API_KEY)


async def budget_left() -> bool:
    return enabled() and await db.spent_today() < config.DAILY_LIMIT_USD


def is_peak(now=None) -> bool:
    """Часы пика у сервиса (по UTC, пн-пт): в это время всё дороже в PRICE_PEAK_X раз."""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    for part in config.PEAK_HOURS_UTC.replace(" ", "").split(","):
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            if start <= now.hour < end:
                return True
    return False


def cost(tok_in: int, tok_out: int, tok_cached: int = 0, now=None, strong: bool = False) -> float:
    """Цена запроса как в счёте сервиса: вход вне кэша, вход из кэша (характер и правила), ответ, плюс часы пика.
    strong: запрос ушёл в сильную модель, у неё свои цены."""
    tok_cached = min(tok_cached, tok_in)
    p_in, p_cache, p_out = ((config.STRONG_PRICE_IN, config.STRONG_PRICE_CACHE, config.STRONG_PRICE_OUT) if strong
                            else (config.PRICE_IN, config.PRICE_CACHE, config.PRICE_OUT))
    usd = ((tok_in - tok_cached) * p_in + tok_cached * p_cache + tok_out * p_out) / 1e6
    return usd * (config.PRICE_PEAK_X if is_peak(now) else 1)


def cached_tokens(usage: dict) -> int:
    """Сколько входа пришло из кэша: у одних сервисов prompt_cache_hit_tokens, у других prompt_tokens_details."""
    details = usage.get("prompt_tokens_details") or {}
    return int(usage.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0)


# вызывается после каждого запроса с ценой и чатом (регистрирует services/plans: дневной лимит пробных чатов)
on_spend = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.AI_BASE_URL,
            headers={"Authorization": f"Bearer {config.AI_API_KEY}"},
            timeout=config.AI_TIMEOUT,
        )
    return _client


async def close() -> None:
    if _client is not None:
        await _client.aclose()


# Чат, для которого сейчас работает бот (ставит GroupTracker и планировщик), и проверка тарифа
# (её регистрирует services/plans): у бесплатных чатов нейросеть выключена или ограничена.
CURRENT_CHAT: ContextVar = ContextVar("current_chat", default=None)
gate = None
# режим «меня обновляют» (services/maint): до этого времени нейросеть не вызывается вообще
PAUSED_UNTIL = 0.0
# почему последний chat() вернул None, и когда подряд не было связи с сервисом (для сообщения владельцу)
LAST_FAIL = ""
NET_FAILS: list[float] = []


def _net_fail() -> None:
    NET_FAILS.append(time.time())
    del NET_FAILS[:-50]


def strong_allowed(row) -> bool:
    """Сильная модель только для чатов с арендой от 30 дней или бессрочных. Пробные, бесплатные и короткие
    аренды на основной модели, чтобы их дневной лимит не кончался к обеду."""
    if row is None:
        return False
    try:
        if not row["approved"] or row["free"] or row["trial"]:
            return False
        if not row["rent_until"]:
            return True   # бессрочно
        days = row["plan_days"]
    except (IndexError, KeyError):
        return False
    if days is None or days < 0:   # выдано до этого обновления: судим по остатку
        return row["rent_until"] - time.time() >= 20 * 86400
    return days >= 30


def net_down_minutes() -> float:
    """Сколько минут подряд нет связи с сервисом нейросети (0, если последний запрос прошёл)."""
    return (time.time() - NET_FAILS[0]) / 60 if len(NET_FAILS) >= 3 else 0.0


# доля ответов людям через сильную модель, 0-100 % (владелец выбирает, хранится в kv strong_share)
STRONG_SHARE = 0
_strong_ok = True   # сильная модель недоступна (неверное имя, нет доступа): дальше всё через основную
# штраф за повторы слов в ответах (frequency/presence penalty); если сервис его не примет, выключаем сами
_penalty_ok = True
# вид запроса для разбивки расхода в админке: reply ответы, memory заметки, results итоги и т.д.
KINDS = {"reply": "💬 ответы в чате", "memory": "🧠 заметки о людях", "results": "📊 итоги дня",
         "event": "🎉 приветствия, вопрос дня, оживление", "quiz": "🎯 викторины", "joke": "😂 шутки",
         "strong": "🧠 ответы сильной моделью",
         "roast": "🔥 прожарки", "summary": "📝 что тут было"}


async def chat_as(kind: str, messages: list[dict], **kw) -> str | None:
    """То же, что chat, но с пометкой, на что запрос (для разбивки расхода)."""
    return await chat(messages, kind=kind, **kw)


async def chat_json_as(kind: str, messages: list[dict], **kw) -> dict | None:
    return await chat_json(messages, kind=kind, **kw)


async def chat(messages: list[dict], max_tokens: int | None = None,
               temperature: float | None = None, json_mode: bool = False, kind: str = "reply",
               penalties: bool = False) -> str | None:
    """Один запрос к модели. None, если ИИ выключен, лимит исчерпан, тариф чата не позволяет или ошибка.
    Почему None, видно в LAST_FAIL: "limit" (лимит, пауза, тариф) или "net" (сервис не ответил или ошибка)."""
    global LAST_FAIL
    LAST_FAIL = "limit"
    if time.time() < PAUSED_UNTIL:
        return None
    if not await budget_left():
        return None
    row = CURRENT_CHAT.get()
    if row is not None and gate is not None and not gate(row):
        return None
    LAST_FAIL = "net"
    global _strong_ok
    # только ответы людям и реплики в разговор; какой именно ответ пойдёт в сильную, решает случай по доле
    strong = bool(penalties and _strong_ok and config.AI_STRONG_MODEL and random.random() * 100 < STRONG_SHARE
                  and strong_allowed(row))
    payload = {
        "model": config.AI_STRONG_MODEL if strong else config.AI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens or config.AI_MAX_TOKENS,
        "temperature": config.AI_TEMPERATURE if temperature is None else temperature,
        "stream": False,
    }
    global _penalty_ok
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if penalties and _penalty_ok and config.AI_FREQ_PENALTY:
        payload["frequency_penalty"] = config.AI_FREQ_PENALTY
        payload["presence_penalty"] = config.AI_PRES_PENALTY
    async with _slots:
        try:
            resp = await _http().post("/chat/completions", json=payload)
            if resp.status_code == 400 and "frequency_penalty" in payload:
                log.warning("Сервис не принял штраф за повторы, выключаю его: %s", resp.text[:200])
                _penalty_ok = False
                payload.pop("frequency_penalty")
                payload.pop("presence_penalty")
                resp = await _http().post("/chat/completions", json=payload)
            if resp.status_code in (400, 401, 403, 404) and strong:
                log.warning("Сильная модель %s не отвечает (%s), перехожу на основную: %s",
                            config.AI_STRONG_MODEL, resp.status_code, resp.text[:200])
                _strong_ok, strong = False, False
                payload["model"] = config.AI_MODEL
                resp = await _http().post("/chat/completions", json=payload)
            if resp.status_code != 200:
                log.warning("ИИ ответил %s: %s", resp.status_code, resp.text[:300])
                _net_fail()
                return None
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("ИИ недоступен: %s", exc)
            _net_fail()
            return None
    NET_FAILS.clear()
    usage = data.get("usage") or {}
    tok_in = int(usage.get("prompt_tokens", 0))
    tok_out = int(usage.get("completion_tokens", 0))
    usd = cost(tok_in, tok_out, cached_tokens(usage), strong=strong)
    await db.add_spend(usd, tok_in, tok_out)
    await db.add_ai_log(row["chat_id"] if row is not None else 0, "strong" if strong else kind, usd)
    if row is not None and on_spend is not None:
        await on_spend(row, usd)
    try:
        return data["choices"][0]["message"]["content"] or None
    except (KeyError, IndexError, TypeError):
        log.warning("Странный ответ ИИ: %s", str(data)[:300])
        return None


def parse_json(text: str | None) -> dict | None:
    """JSON из ответа модели. Модель иногда оборачивает его в ```json ... ```, это тоже понимаем."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


async def chat_json(messages: list[dict], max_tokens: int = 600, temperature: float = 0.9,
                    kind: str = "reply") -> dict | None:
    return parse_json(await chat(messages, max_tokens=max_tokens, temperature=temperature, json_mode=True, kind=kind))
