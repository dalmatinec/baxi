"""Лицензия копии white label и связь с основным ботом через файлы в папке копии:
  license.json   пишет основной бот: до какого числа оплачено, лимит чатов, включена ли копия
  heartbeat.json пишет сама копия раз в минуту: жива ли, сколько чатов, расход ИИ
Основной бот (EDITION=main) лицензию не проверяет."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from aiogram import Bot

from bot import config, db, notify

log = logging.getLogger(__name__)

WARN_DAYS = 3
_state = {"paid_until": 0.0, "max_chats": 0, "active": False, "loaded": False}
_warned_day = ""


def folder(name: str | None = None) -> Path:
    return config.INSTANCES_DIR / (name or config.INSTANCE_NAME)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load() -> None:
    if config.IS_MAIN:
        return
    data = read_json(folder() / "license.json")
    _state.update(paid_until=float(data.get("paid_until", 0)), max_chats=int(data.get("max_chats", 0)),
                  active=bool(data.get("active", True)) and bool(data), loaded=True)


def sleeping() -> bool:
    """Копия спит: не оплачена, остановлена владельцем сети или лицензии нет."""
    if config.IS_MAIN:
        return False
    if not _state["loaded"]:
        load()
    return not _state["active"] or _state["paid_until"] < time.time()


def chat_limit() -> int:
    """Сколько чатов можно по тарифу (0 = без лимита)."""
    return 0 if config.IS_MAIN else _state["max_chats"]


def until_text(ts: float) -> str:
    return datetime.fromtimestamp(ts, config.TZ).strftime("%d.%m.%Y") if ts else "-"


async def tick(bot: Bot) -> None:
    """Копия: перечитать лицензию, отметиться, предупредить своего владельца об оплате."""
    global _warned_day
    if config.IS_MAIN:
        return
    load()
    me = await bot.me()
    try:
        write_json(folder() / "heartbeat.json", {
            "ts": time.time(), "username": me.username, "chats": len(await db.list_chats()),
            "ai_today": round(await db.spent_today(), 4)})
    except OSError as exc:
        log.warning("Не записал heartbeat: %s", exc)
    today = db.today()
    if _warned_day == today:
        return
    left = _state["paid_until"] - time.time()
    if sleeping():
        _warned_day = today
        await notify.owners(bot, "⛔️ Бот на паузе: подписка не оплачена. В чатах я молчу. "
                                 "Чтобы продлить, напиши тому, у кого брал бота.")
    elif left < WARN_DAYS * 86400:
        _warned_day = today
        await notify.owners(bot, f"📅 Подписка на бота заканчивается {until_text(_state['paid_until'])}. "
                                 "Не забудь продлить, иначе бот уснёт.")


# ---------- для основного бота: список копий и управление ----------

def clients() -> list[dict]:
    out = []
    base = config.INSTANCES_DIR
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir() and (p / ".env").exists()):
        lic = read_json(d / "license.json")
        beat = read_json(d / "heartbeat.json")
        out.append({"name": d.name, "license": lic, "beat": beat,
                    "alive": time.time() - float(beat.get("ts", 0)) < 180})
    return out


def update_license(name: str, **changes) -> dict:
    path = folder(name) / "license.json"
    lic = read_json(path)
    lic.update(changes)
    write_json(path, lic)
    return lic


async def remind_main(bot: Bot) -> None:
    """Основной бот: раз в день напомнить владельцу, у кого из клиентов скоро конец оплаты."""
    global _warned_day
    if not config.IS_MAIN or _warned_day == db.today():
        return
    _warned_day = db.today()
    soon = []
    for c in clients():
        until = float(c["license"].get("paid_until", 0))
        if c["license"].get("active", True) and until - time.time() < WARN_DAYS * 86400:
            soon.append(f"• {c['name']}: до {until_text(until)}")
    if soon:
        await notify.owners(bot, "💼 <b>Клиентам скоро продлевать:</b>\n" + "\n".join(soon))
