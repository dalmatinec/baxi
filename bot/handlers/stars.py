"""Магазин за звёзды: личные товары и донаты в личке, оплата, выдача покупок, топ донатеров."""

import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message,
                           PreCheckoutQuery, User)

from bot import config, db, notify
from bot.services import menu, stars
from bot.textutil import esc, full_name, mention

log = logging.getLogger(__name__)
router = Router(name="stars")


class VipLook(StatesGroup):
    emoji = State()
    nick = State()


def _kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t, callback_data=d, style=s[0] if s else None) for t, d, *s in row] for row in rows])


async def shop_rows(user: User) -> list[list[InlineKeyboardButton]]:
    items = await stars.items_map()
    rows = []
    if await stars.has_look(user.id):
        rows.append([InlineKeyboardButton(text="✨ Мой ник и эмодзи", callback_data="st:vip", style="success")])
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
        lines.append(f"{place} {mention(r['user_id'], names[r['user_id']])}: <b>{r['stars']} ⭐</b>")
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
    await message.answer(result, parse_mode="HTML")


# ---------- свой ник: премиум-эмодзи и ник у имени (за монеты навсегда или по старому VIP) ----------

async def look_screen(target: Message | CallbackQuery, user: User) -> None:
    perks = await db.get_perks(user.id)
    if not await stars.has_look(user.id):
        text = ("✨ <b>Свой ник</b>\n\nПремиум-эмодзи и жирный ник у имени везде, где бот тебя упоминает. "
                "Покупается навсегда за монеты: напиши в своём чате <b>магазин</b>.")
        kb = _kb([[("⬅️ Магазин", "sc:shop")]])
    else:
        until = "навсегда" if perks["look_forever"] else \
            "до " + datetime.fromtimestamp(perks["vip_until"], config.TZ).strftime("%d.%m.%Y")
        text = ("✨ <b>Мой ник</b>\n\n"
                f"Так тебя видят в чатах:\n{mention(user.id, full_name(user.first_name, user.last_name))}\n\n"
                "Это везде, где бот тебя упоминает: топы, репутация, итоги, игры, пары.\n"
                f"Действует <b>{until}</b>.")
        kb = _kb([[("✨ Свой эмодзи", "st:ve", "primary"), ("✏️ Ник", "st:vn", "primary")],
                  [("↩️ Сбросить вид", "st:vr")], [("⬅️ Магазин", "sc:shop")]])
    if isinstance(target, CallbackQuery):
        await target.answer()
        try:
            return await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            target = target.message
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "st:vip")
async def cb_vip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await look_screen(cb, cb.from_user)


@router.callback_query(F.data.in_({"st:ve", "st:vn"}))
async def cb_vip_edit(cb: CallbackQuery, state: FSMContext) -> None:
    if not await stars.has_look(cb.from_user.id):
        return await cb.answer("свой ник не куплен", show_alert=True)
    emoji = cb.data == "st:ve"
    await state.set_state(VipLook.emoji if emoji else VipLook.nick)
    await cb.answer()
    await cb.message.answer(
        "✨ Пришли сообщение с одним <b>премиум-эмодзи</b> (из любого набора), он встанет слева от твоего имени. "
        "Убрать и вернуть корону: пришли минус." if emoji else
        "✏️ Пришли ник, который будет вместо имени, любым шрифтом (до 24 символов, без ссылок и @). "
        "Он будет жирным. Вернуть имя: пришли минус.",
        parse_mode="HTML", reply_markup=_kb([[("Отмена", "st:vip")]]))


@router.message(VipLook.emoji)
async def on_vip_emoji(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip() == "-":
        await db.set_perks(message.from_user.id, emoji_id="", emoji_alt="")
    else:
        found = stars.custom_emoji(message)
        if not found:
            return await message.answer("Не вижу премиум-эмодзи. Пришли именно его (обычные эмодзи не подойдут) "
                                        "или минус.")
        await db.set_perks(message.from_user.id, emoji_id=found[0], emoji_alt=found[1])
    await state.clear()
    await stars.refresh_looks()
    await look_screen(message, message.from_user)


@router.message(VipLook.nick, F.text)
async def on_vip_nick(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "-":
        nick = ""
    else:
        nick = stars.clean_nick(message.text)
        if not nick:
            return await message.answer("Не подходит: до 24 символов, без ссылок и @. Попробуй ещё раз.")
    await db.set_perks(message.from_user.id, nick=nick)
    await state.clear()
    await stars.refresh_looks()
    await look_screen(message, message.from_user)


@router.callback_query(F.data == "st:vr")
async def cb_vip_reset(cb: CallbackQuery) -> None:
    await db.set_perks(cb.from_user.id, emoji_id="", emoji_alt="", nick="")
    await stars.refresh_looks()
    await look_screen(cb, cb.from_user)
