"""Запросы к нейросети через API в формате OpenAI.
Следит за дневным лимитом трат: кончился лимит, функции возвращают None,
и бот отвечает фразами из базы."""

import asyncio
import json
import logging
from contextvars import ContextVar
import re

import httpx

from bot import config, db

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_slots = asyncio.Semaphore(3)  # не больше 3 запросов к ИИ одновременно


def enabled() -> bool:
    return bool(config.AI_API_KEY)


async def budget_left() -> bool:
    return enabled() and await db.spent_today() < config.DAILY_LIMIT_USD


def cost(tok_in: int, tok_out: int) -> float:
    return tok_in * config.PRICE_IN / 1e6 + tok_out * config.PRICE_OUT / 1e6


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


async def chat(messages: list[dict], max_tokens: int | None = None,
               temperature: float | None = None, json_mode: bool = False) -> str | None:
    """Один запрос к модели. None, если ИИ выключен, лимит исчерпан, тариф чата не позволяет или ошибка."""
    if not await budget_left():
        return None
    row = CURRENT_CHAT.get()
    if row is not None and gate is not None and not gate(row):
        return None
    payload = {
        "model": config.AI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens or config.AI_MAX_TOKENS,
        "temperature": config.AI_TEMPERATURE if temperature is None else temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with _slots:
        try:
            resp = await _http().post("/chat/completions", json=payload)
            if resp.status_code != 200:
                log.warning("ИИ ответил %s: %s", resp.status_code, resp.text[:300])
                return None
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("ИИ недоступен: %s", exc)
            return None
    usage = data.get("usage") or {}
    tok_in = int(usage.get("prompt_tokens", 0))
    tok_out = int(usage.get("completion_tokens", 0))
    await db.add_spend(cost(tok_in, tok_out), tok_in, tok_out)
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


async def chat_json(messages: list[dict], max_tokens: int = 600, temperature: float = 0.9) -> dict | None:
    return parse_json(await chat(messages, max_tokens=max_tokens, temperature=temperature, json_mode=True))
