"""Магазин за звёзды: личные товары и донаты в личке, оплата, выдача покупок, топ донатеров."""

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery, User)

from bot import db, notify
from bot.services import menu, stars
from bot.textutil import esc, full_name

log = logging.getLogger(__name__)
router = Router(name="stars")


class TitleSet(StatesGroup):
    text = State()


def _kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t, callback_data=d, style=s[0] if s else None) for t, d, *s in row] for row in rows])


async def shop_rows(user: User) -> list[list[InlineKeyboardButton]]:
    items = await stars.items_map()
    rows = []
    for key, style in (("vip", "success"), ("shield", "primary")):
        if key in items:
            rows.append([InlineKeyboardButton(text=f"{items[key]['title']} · {items[key]['stars']} ⭐",
                                              callback_data=f"st:b:{key}", style=style)])
    if any(k.startswith("don") for k in items):
        rows.append([InlineKeyboardButton(text="💛 Поддержать бота", callback_data="st:don")])
    return rows


menu.EXTRA_ROWS["shop"] = shop_rows


async def _invoice(bot: Bot, chat_id: int, key: str) -> None:
    item = (await stars.items_map()).get(key)
    if not item:
        return
    await bot.send_invoice(chat_id, title=item["title"][:32], description=stars.item_text(key)[:255], payload=key,
                           currency="XTR", prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])])


@router.callback_query(F.data.startswith("st:b:"))
async def cb_buy(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    await _invoice(bot, cb.from_user.id, cb.data[5:])


@router.callback_query(F.data == "st:don")
async def cb_donate(cb: CallbackQuery) -> None:
    items = await stars.items_map()
    rows = [[(f"{i['title']} ⭐", f"st:b:{k}", "success")] for k, i in items.items() if k.startswith("don")]
    await cb.answer()
    await cb.message.edit_text("💛 <b>Поддержать бота</b>\n\nВсе донатеры попадают в топ, а самые щедрые "
                               "красуются там на первых местах.", parse_mode="HTML",
                               reply_markup=_kb(rows + [[("👑 Топ донатеров", "act:donors")], [("⬅️ Магазин", "sc:shop")]]))


async def donors_text(user_ids: list[int] | None = None, viewer: int | None = None) -> str:
    rows = await db.donors_top(10, user_ids)
    if not rows:
        return ("👑 <b>Топ донатеров</b>\n\nПока пусто, первое место свободно 👀\n"
                "Поддержать бота: личка бота → Магазин.")
    names = await stars.decorate(rows)
    medals = ["🥇", "🥈", "🥉"]
    total = await db.stars_total()
    lines = ["👑 <b>Топ донатеров</b>", f"Всего собрано: <b>{total} ⭐</b>", ""]
    for i, r in enumerate(rows):
        place = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{place} {esc(names[r['user_id']])}: <b>{r['stars']} ⭐</b>")
    if viewer and viewer not in [r["user_id"] for r in rows]:
        lines += ["", "Тебя в топе пока нет. Одно пожертвование, и ты здесь 💛"]
    return "\n".join(lines)


@router.callback_query(F.data == "act:donors")
async def cb_donors(cb: CallbackQuery) -> None:
    kb = _kb([[("💛 Поддержать", "st:don", "success")], [("⬅️ В меню", "sc:start")]])
    await cb.answer()
    text = await donors_text(viewer=cb.from_user.id)
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, bot: Bot) -> None:
    problem = await stars.check(bot, query.invoice_payload, query.from_user.id)
    if problem:
        return await query.answer(ok=False, error_message=problem)
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message, bot: Bot, state: FSMContext) -> None:
    pay = message.successful_payment
    user = message.from_user
    name = full_name(user.first_name, user.last_name)
    p = stars.parse_payload(pay.invoice_payload)
    await db.add_star_payment(user.id, name, p["item"], pay.total_amount, pay.telegram_payment_charge_id,
                              pay.invoice_payload)
    await notify.owners(bot, f"⭐ {esc(name)} заплатил {pay.total_amount} ⭐ за {esc(p['item'])}")
    try:
        result = await stars.apply(bot, pay.invoice_payload, user.id, name)
    except Exception:
        log.exception("Покупка %s не выполнилась", pay.invoice_payload)
        await notify.owners(bot, f"⚠️ Оплаченная покупка {esc(p['item'])} от {esc(name)} не выполнилась. "
                                 "Верни звёзды: /admin → Монетизация → Платежи.")
        return await message.answer("Что-то пошло не так, звёзды вернём. Если долго нет ответа: /support")
    if result == "ask_title":
        await state.set_state(TitleSet.text)
        await state.update_data(chat_id=p["chat_id"])
        return await message.answer(f"🏷 Оплачено! Придумай должность: до {stars.TITLE_MAX} символов, "
                                    "без эмодзи. Например: Король чата")
    await message.answer(result, parse_mode="HTML")


@router.message(TitleSet.text, F.text)
async def on_title(message: Message, bot: Bot, state: FSMContext) -> None:
    title = stars.clean_title(message.text)
    if not title:
        return await message.answer(f"Не подходит: до {stars.TITLE_MAX} символов, без эмодзи, ссылок и @. "
                                    "Попробуй ещё раз.")
    chat_id = (await state.get_data())["chat_id"]
    user = message.from_user
    try:
        await stars.give_title(bot, chat_id, user.id, full_name(user.first_name, user.last_name), title)
    except Exception as exc:
        log.warning("Не выдал должность: %s", exc)
        return await message.answer("Telegram не дал поставить такую подпись. Попробуй другой текст.")
    await state.clear()
    await message.answer(f"🏷 Готово! В чате ты теперь «{esc(title)}» на {stars.POS_DAYS} дней.", parse_mode="HTML")
