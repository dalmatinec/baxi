"""Супер-админка → Клиенты (white label): кто жив, до какого числа оплачено, продление, пауза, лимит чатов.
Новую копию создаёт скрипт на сервере: bash /opt/linkhub/deploy/client.sh add имя"""

import time

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.services import license
from bot.textutil import esc

router = Router(name="admin-clients")
LIMITS = [1, 3, 5, 10, 0]


def _status(c: dict) -> str:
    lic = c["license"]
    if not lic.get("active", True):
        return "⏸"
    if float(lic.get("paid_until", 0)) < time.time():
        return "⛔️"
    return "🟢" if c["alive"] else "🔴"


@router.callback_query(F.data == "cl:list")
async def cb_list(cb: CallbackQuery) -> None:
    items = license.clients()
    rows = [[(f"{_status(c)} {c['name']} · до {license.until_text(float(c['license'].get('paid_until', 0)))}",
              f"cl:o:{c['name']}")] for c in items]
    text = ("💼 <b>Клиенты white label</b>\n\n🟢 работает · 🔴 не отвечает · ⛔️ не оплачен · ⏸ на паузе\n\n"
            "Новый клиент: на сервере\n<code>bash /opt/linkhub/deploy/client.sh add имя</code>")
    if not items:
        text += "\n\nПока ни одного."
    await show(cb, text, kb(rows + [[BACK_MENU]]))


async def _card(target, name: str) -> None:
    c = next((x for x in license.clients() if x["name"] == name), None)
    if c is None:
        return await show(target, "Клиент не найден", kb([[("⬅️ Клиенты", "cl:list")]]))
    lic, beat = c["license"], c["beat"]
    limit = int(lic.get("max_chats", 0))
    seen = int(time.time() - float(beat.get("ts", 0))) if beat else None
    text = (f"💼 <b>{esc(name)}</b> {_status(c)}\n\n"
            f"Бот: @{esc(beat.get('username', '?'))}\n"
            f"Оплачено до: <b>{license.until_text(float(lic.get('paid_until', 0)))}</b>\n"
            f"Чатов: {beat.get('chats', '?')} из {limit or '∞'}\n"
            f"ИИ сегодня: ${beat.get('ai_today', 0)}\n"
            f"На связи: {f'{seen // 60} мин назад' if seen is not None else 'ни разу'}")
    await show(target, text, kb([
        [("➕ 30 дней", f"cl:add:{name}:30", "success"), ("➕ 7 дней", f"cl:add:{name}:7")],
        [(f"💬 Лимит чатов: {limit or '∞'}", f"cl:lim:{name}")],
        [("⏸ Пауза", f"cl:off:{name}", "danger") if lic.get("active", True) else ("▶️ Включить", f"cl:on:{name}",
                                                                                   "success")],
        [("⬅️ Клиенты", "cl:list")],
    ]))


@router.callback_query(F.data.startswith("cl:o:"))
async def cb_open(cb: CallbackQuery) -> None:
    await _card(cb, cb.data[5:])


@router.callback_query(F.data.startswith(("cl:add:", "cl:lim:", "cl:off:", "cl:on:")))
async def cb_change(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    op, name = parts[1], parts[2]
    c = next((x for x in license.clients() if x["name"] == name), None)
    if c is None:
        return await cb.answer("Клиент не найден")
    lic = c["license"]
    if op == "add":
        start = max(time.time(), float(lic.get("paid_until", 0)))
        lic = license.update_license(name, paid_until=start + int(parts[3]) * 86400, active=True)
        await cb.answer(f"Оплачено до {license.until_text(lic['paid_until'])}")
    elif op == "lim":
        cur = int(lic.get("max_chats", 0))
        nxt = LIMITS[(LIMITS.index(cur) + 1) % len(LIMITS)] if cur in LIMITS else 3
        license.update_license(name, max_chats=nxt)
    elif op in ("off", "on"):
        license.update_license(name, active=op == "on")
        await cb.answer("Копия на паузе, в чатах молчит" if op == "off" else "Копия снова работает")
    await _card(cb, name)
