"""Магазин за звёзды в личке, оплата (pre_checkout и successful_payment), топ донатеров."""

import logging
import time

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery, User

from bot import db, notify
from bot.services import menu, stars
from bot.textutil import esc, full_name

log = logging.getLogger(__name__)
router = Router(name="stars")


class TitleSet(StatesGroup):
    text = State()


async def shop_rows(user: User) -> list[list[InlineKeyboardButton]]:
    await db.seed_shop(stars.DEFAULT_ITEMS)
    rows = []
    for item in await db.shop_items():
        style = "success" if item["key"].startswith("don") else "primary"
        rows.append([InlineKeyboardButton(text=f"{item['title']} · {item['stars']} ⭐",
                                          callback_data=f"st:b:{item['key']}", style=style)])
    return rows


menu.EXTRA_ROWS["shop"] = shop_rows


@router.callback_query(F.data.startswith("st:b:"))
async def cb_buy(cb: CallbackQuery, bot: Bot) -> None:
    key = cb.data[5:]
    if key == "roast_full":
        return await cb.answer(stars.item_text("roast_full"), show_alert=True)
    await cb.answer()
    await stars.invoice(bot, cb.from_user.id, key)


async def donors_text(user_ids: list[int] | None = None) -> str:
    rows = await db.donors_top(10, user_ids)
    if not rows:
        return "👑 <b>Топ донатеров</b>\n\nПока пусто. Стань первым: Меню → Магазин"
    names = await stars.decorate(rows)
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else f'{i + 1}.'} {esc(names[r['user_id']])}: <b>{r['stars']}</b> ⭐"
             for i, r in enumerate(rows)]
    return "👑 <b>Топ донатеров</b>\n\n" + "\n".join(lines)


@router.callback_query(F.data == "act:donors")
async def cb_donors(cb: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛒 В магазин", callback_data="sc:shop", style="success"),
        InlineKeyboardButton(text="⬅️ В меню", callback_data="sc:start")]])
    await cb.answer()
    try:
        await cb.message.edit_text(await donors_text(), parse_mode="HTML", reply_markup=kb)
    except Exception:
        await cb.message.answer(await donors_text(), parse_mode="HTML", reply_markup=kb)


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    payload = query.invoice_payload
    if payload.startswith("roast:"):
        target_id = int(payload.split(":")[2])
        if await stars.shielded(target_id):
            return await query.answer(ok=False, error_message="У этого человека появился щит от прожарки 🛡")
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_paid(message: Message, bot: Bot, state: FSMContext) -> None:
    pay = message.successful_payment
    user = message.from_user
    name = full_name(user.first_name, user.last_name)
    payload = pay.invoice_payload
    item = payload.split(":")[0]
    await db.add_star_payment(user.id, name, item, pay.total_amount, pay.telegram_payment_charge_id, payload)
    await notify.owners(bot, f"⭐ {esc(name)} заплатил {pay.total_amount} ⭐ за {esc(item)}")
    now = time.time()
    if item.startswith("don"):
        await message.answer(f"💛 Спасибо за поддержку, {esc(name)}! Ты в топе донатеров.", parse_mode="HTML")
    elif item == "shield":
        perks = await db.get_perks(user.id)
        start = max(now, perks["shield_until"] if perks else 0)
        await db.set_perks(user.id, shield_until=start + stars.SHIELD_DAYS * 86400)
        await message.answer(f"🛡 Щит включён на {stars.SHIELD_DAYS} дней. Теперь тебя никто не прожарит.")
    elif item == "title":
        await state.set_state(TitleSet.text)
        await message.answer("👑 Придумай титул: до 20 символов, например «Король чата». Пришли его сообщением.")
    elif item == "roast":
        _, chat_id, target_id = payload.split(":")
        await message.answer("🔥 Оплата прошла, жарю в чате!")
        try:
            await stars.do_full_roast(bot, int(chat_id), int(target_id), name)
        except Exception:
            log.exception("Прожарка по полной не вышла")
            await notify.owners(bot, f"⚠️ Оплаченная прожарка в чате {chat_id} не вышла, верни звёзды в админке")


@router.message(TitleSet.text, F.text)
async def on_title(message: Message, state: FSMContext) -> None:
    title = " ".join(message.text.split())[:20]
    if not title or "http" in title.lower() or "@" in title or "t.me" in title.lower():
        return await message.answer("Без ссылок и @, просто слова. Попробуй ещё раз.")
    await state.clear()
    await db.set_perks(message.from_user.id, title=title, title_until=time.time() + stars.TITLE_DAYS * 86400)
    await message.answer(f"👑 Готово! Теперь в топах ты «{esc(title)}» ещё {stars.TITLE_DAYS} дней.",
                         parse_mode="HTML")
