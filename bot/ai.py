"""Запросы к нейросети через API в формате OpenAI (у DeepSeek такой же).
Следит за дневным лимитом трат: кончился лимит, функции возвращают None,
и бот отвечает фразами из базы."""

import asyncio
import logging

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


async def chat(messages: list[dict], max_tokens: int | None = None,
               temperature: float | None = None) -> str | None:
    """Один запрос к модели. None, если ИИ выключен, лимит исчерпан или ошибка."""
    if not await budget_left():
        return None
    payload = {
        "model": config.AI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens or config.AI_MAX_TOKENS,
        "temperature": config.AI_TEMPERATURE if temperature is None else temperature,
        "stream": False,
    }
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
