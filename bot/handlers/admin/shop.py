"""Супер-админка → Магазин звёзд: цены товаров, включение, последние платежи и возврат звёзд."""

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config, db
from bot.handlers.admin.common import BACK_MENU, kb, onoff, show
from bot.services import stars
from bot.textutil import esc, short

router = Router(name="admin-shop")


class StarPrice(StatesGroup):
    value = State()


@router.callback_query(F.data == "sh:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await db.seed_shop(stars.DEFAULT_ITEMS)
    rows = [[(f"{'' if i['enabled'] else '⏸ '}{short(i['title'], 30)} · {i['stars']}⭐", f"sh:i:{i['key']}")]
            for i in await db.shop_items(enabled_only=False)]
    total = sum(p["stars"] for p in await db.star_payments(1000) if not p["refunded"])
    await show(cb, f"⭐ <b>Магазин звёзд</b>\n\nВсего получено: <b>{total} ⭐</b> (последние 1000 платежей)\n"
                   "Вывод звёзд: Telegram → бот → Баланс → Вывести через Fragment.",
               kb(rows + [[("🧾 Платежи и возвраты", "sh:pay", "primary")], [BACK_MENU]]))


async def _item(target, key: str) -> None:
    i = await db.shop_item(key)
    if not i:
        return
    await show(target, f"{esc(i['title'])}\n\nЦена: <b>{i['stars']} ⭐</b>\nВ продаже: {onoff(i['enabled'])}\n\n"
                       f"<i>{esc(stars.item_text(key))}</i>",
               kb([[("💵 Цена", f"sh:p:{key}"), ("⏸ Скрыть" if i["enabled"] else "▶️ Продавать", f"sh:e:{key}")],
                   [("⬅️ Магазин", "sh:menu")]]))


@router.callback_query(F.data.startswith("sh:i:"))
async def cb_item(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _item(cb, cb.data[5:])


@router.callback_query(F.data.startswith("sh:e:"))
async def cb_toggle(cb: CallbackQuery) -> None:
    key = cb.data[5:]
    i = await db.shop_item(key)
    if i:
        await db.update_shop_item(key, enabled=0 if i["enabled"] else 1)
    await _item(cb, key)


@router.callback_query(F.data.startswith("sh:p:"))
async def cb_price(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data[5:]
    await state.set_state(StarPrice.value)
    await state.update_data(key=key)
    await show(cb, "💵 Пришли новую цену в звёздах, целое число от 1 до 10000", kb([[("Отмена", f"sh:i:{key}")]]))


@router.message(StarPrice.value, F.text)
async def on_price(message: Message, state: FSMContext) -> None:
    if not message.text.strip().isdigit() or not 1 <= int(message.text.strip()) <= 10000:
        return await message.answer("Нужно целое число от 1 до 10000")
    key = (await state.get_data())["key"]
    await state.clear()
    await db.update_shop_item(key, stars=int(message.text.strip()))
    await _item(message, key)


@router.callback_query(F.data == "sh:pay")
async def cb_payments(cb: CallbackQuery) -> None:
    rows = []
    for p in await db.star_payments(20):
        when = datetime.fromtimestamp(p["ts"], config.TZ).strftime("%d.%m %H:%M")
        mark = "↩️ " if p["refunded"] else ""
        rows.append([(f"{mark}{when} {short(p['name'], 14)} · {p['stars']}⭐ · {p['item']}", f"sh:o:{p['id']}")])
    await show(cb, "🧾 <b>Последние платежи звёздами</b>" if rows else "Платежей пока нет.",
               kb(rows + [[("⬅️ Магазин", "sh:menu")]]))


@router.callback_query(F.data.startswith("sh:o:"))
async def cb_payment(cb: CallbackQuery) -> None:
    p = await db.get_star_payment(int(cb.data[5:]))
    if not p:
        return await cb.answer()
    await show(cb, f"⭐ <b>{p['stars']} звёзд</b> за {esc(p['item'])}\nОт: {esc(p['name'])} (<code>{p['user_id']}</code>)\n"
                   f"Статус: {'возвращено' if p['refunded'] else 'получено'}",
               kb([[("↩️ Вернуть звёзды", f"sh:r:{p['id']}", "danger")] if not p["refunded"] else [],
                   [("⬅️ Платежи", "sh:pay")]]))


@router.callback_query(F.data.startswith("sh:r:"))
async def cb_refund(cb: CallbackQuery, bot: Bot) -> None:
    p = await db.get_star_payment(int(cb.data[5:]))
    if not p or p["refunded"]:
        return await cb.answer()
    try:
        await bot.refund_star_payment(p["user_id"], p["charge_id"])
    except Exception as exc:
        return await cb.answer(f"Не вышло: {str(exc)[:150]}", show_alert=True)
    await db.mark_refunded(p["id"])
    if p["item"] == "shield":
        await db.set_perks(p["user_id"], shield_until=0)
    elif p["item"] == "vip":
        await db.set_perks(p["user_id"], vip_until=0)
        await stars.refresh_looks()
    elif p["item"] == "title":
        await db.set_perks(p["user_id"], title="", title_until=0)
    await cb.answer("↩️ Звёзды возвращены")
    await cb_payments(cb)
