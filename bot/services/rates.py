"""Курсы валют и крипты одной карточкой: «курс», «курс валют», «курс доллара», «крипта», /rates.
Без нейросети и без ключей.

Валюты: официальный курс Нацбанка РК (nationalbank.kz, RSS), обновляется раз в день, кеш 30 минут.
Крипта: CoinGecko (USDT в тенге и долларах, BTC, TON, ETH в долларах, изменение за сутки), кеш 5 минут.
Если один источник не ответил, показываем то, что есть."""

import logging
import re
import time
from datetime import datetime

import httpx

from bot import config

log = logging.getLogger(__name__)

NBK_URL = "https://nationalbank.kz/rss/rates_all.xml"
GECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

FIAT = [("USD", "🇺🇸", "Доллар"), ("EUR", "🇪🇺", "Евро"), ("CNY", "🇨🇳", "Юань"), ("RUB", "🇷🇺", "Рубль")]
CRYPTO = [("bitcoin", "₿", "Bitcoin"), ("the-open-network", "💎", "TON"), ("ethereum", "🔷", "Ethereum")]

_cache: dict[str, tuple[float, dict | None]] = {}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10, headers={"User-Agent": "baxi-bot"})
    return _client


def arrow(pct: float | None) -> str:
    """▲0.3% / ▼0.1%; совсем мелкие изменения не показываем."""
    if pct is None or abs(pct) < 0.05:
        return ""
    return f" {'▲' if pct > 0 else '▼'}{abs(pct):.1f}%"


def money(v: float) -> str:
    """59 288, 1 649, 5.40, 0.93: тысячи через пробел, мелочь с копейками."""
    if v >= 100:
        return f"{round(v):,}".replace(",", " ")
    return f"{v:.2f}"


def parse_nbk(xml: str) -> dict:
    """RSS Нацбанка → {"USD": (курс за 1, изменение %)}."""
    out = {}
    def tag(item: str, name: str) -> str:
        m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
        return m.group(1).strip() if m else ""

    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        code = tag(item, "title")
        try:
            rate, quant = float(tag(item, "description")), float(tag(item, "quant") or 1)
            change = float(tag(item, "change") or 0)
        except ValueError:
            continue
        prev = rate - change
        out[code] = (rate / quant, change / prev * 100 if prev else None)
    return out


async def _fiat() -> dict | None:
    hit = _cache.get("fiat")
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    data = None
    try:
        resp = await _http().get(NBK_URL)
        if resp.status_code == 200:
            data = parse_nbk(resp.text) or None
    except httpx.HTTPError as exc:
        log.info("Курсы Нацбанка не ответили: %s", exc)
    if data:
        _cache["fiat"] = (time.time(), data)
    return data or (hit[1] if hit else None)   # лучше вчерашний курс, чем никакого


async def _crypto() -> dict | None:
    hit = _cache.get("crypto")
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    data = None
    try:
        ids = ",".join(["tether"] + [c for c, _, _ in CRYPTO])
        resp = await _http().get(GECKO_URL, params={"ids": ids, "vs_currencies": "usd,kzt",
                                                    "include_24hr_change": "true"})
        if resp.status_code == 200:
            data = resp.json() or None
    except (httpx.HTTPError, ValueError) as exc:
        log.info("Курсы крипты не ответили: %s", exc)
    if data:
        _cache["crypto"] = (time.time(), data)
    return data or (hit[1] if hit else None)


def card(fiat: dict | None, crypto: dict | None, now: datetime | None = None) -> str:
    now = now or datetime.now(config.TZ)
    lines = [f"💱 <b>Курс валют</b> · {now:%H:%M}", ""]
    if fiat:
        for code, flag, name in FIAT:
            if code in fiat:
                rate, pct = fiat[code]
                lines.append(f"{flag} {name}: <b>{rate:.2f} ₸</b>{arrow(pct)}")
    else:
        lines.append("курсы Нацбанка сейчас не отвечают")
    if crypto:
        lines += ["", "🪙 <b>Крипта</b>"]
        t = crypto.get("tether") or {}
        if t.get("kzt"):
            lines.append(f"💵 USDT (TRC20): <b>{money(t['kzt'])} ₸</b> · ${t.get('usd', 1):.2f}")
        for cid, emoji, name in CRYPTO:
            c = crypto.get(cid) or {}
            if c.get("usd"):
                lines.append(f"{emoji} {name}: <b>${money(c['usd'])}</b>{arrow(c.get('usd_24h_change'))}")
    lines += ["", "<i>по курсу Нацбанка РК · крипта по CoinGecko, ▲▼ за сутки</i>"]
    return "\n".join(lines)


async def rates_html() -> str:
    return card(await _fiat(), await _crypto())


HELP = ("💱 <b>Курсы</b>\n\n"
        "Напиши в чат <b>курс</b>, <b>курс доллара</b> или <b>крипта</b>, либо /rates.\n"
        "Покажу доллар, евро, юань и рубль в тенге по курсу Нацбанка и крипту: USDT, Bitcoin, TON, Ethereum.")
