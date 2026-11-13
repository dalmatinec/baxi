"""Заказ рекламы в личке: формат → пост → кнопки → предпросмотр → на проверку → оплата."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from bot import config, db
from bot.handlers.admin.ads import BUTTONS_HINT
from bot.services import adorders, menu
from bot.services.ads import extract_post, send_ad
from bot.textutil import esc, full_name, parse_buttons

router = Router(name="adshop")
router.message.filter(F.chat.type == "private")


class Order(StatesGroup):
    post = State()
    buttons = State()


def _kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t, callback_data=d, style=s[0] if s else None) for t, d, *s in row]
        for row in rows if row])


async def product_rows(user: User) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text=f"{p['title']} · ${p['price']:g}", callback_data=f"ao:p:{p['id']}",
                                  style="primary")]
            for p in await db.products() if p["kind"] != "pin_channel" or config.AD_CHANNEL_ID]


menu.EXTRA_ROWS["ads"] = product_rows


@router.callback_query(F.data.startswith("ao:p:"))
async def cb_product(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    product = await db.get_product(int(cb.data.split(":")[2]))
    if not product or not product["enabled"]:
        return await cb.answer("Этот формат сейчас недоступен", show_alert=True)
    reach = await db.reach()
    days = f"\n📅 Дней подряд: <b>{product['days']}</b>" if product["days"] > 1 else ""
    audience = (f"{reach['dm']} человек в личке" if product["kind"] == "dm"
                else f"{reach['chats']} чатов, {reach['members']} участников")
    text = (f"{esc(product['title'])}\n\n"
            f"Что это: {adorders.KIND_TEXT.get(product['kind'], '')}.{days}\n"
            f"👥 Охват: <b>{audience}</b>\n"
            f"💵 Цена: <b>{product['price']:g} USDT</b>\n\n"
            "Дальше пришлёшь пост и кнопки, увидишь предпросмотр. После проверки модератором придут реквизиты.")
    await cb.answer()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_kb([
        [("✅ Заказать", f"ao:n:{product['id']}", "success")], [("⬅️ Форматы", "sc:ads")]]))


@router.callback_query(F.data.startswith("ao:n:"))
async def cb_new(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[2])
    await state.set_state(Order.post)
    await state.update_data(pid=pid)
    await cb.answer()
    await cb.message.answer("📝 <b>Шаг 1 из 2: пост</b>\n\nПришли пост одним сообщением: текст, фото, видео или гифку "
                            "с подписью. Жирный, ссылки и премиум-эмодзи сохранятся.",
                            parse_mode="HTML", reply_markup=_kb([[("❌ Отмена", "sc:ads")]]))


@router.message(Order.post)
async def on_post(message: Message, state: FSMContext) -> None:
    post = extract_post(message)
    if isinstance(post, str):
        return await message.answer(post)
    kind, file_id, html = post
    await state.update_data(media_kind=kind, file_id=file_id, html=html)
    await state.set_state(Order.buttons)
    await message.answer("🔘 <b>Шаг 2 из 2: кнопки</b>\n\n" + BUTTONS_HINT, parse_mode="HTML",
                         reply_markup=_kb([[("Без кнопок", "ao:nob")], [("❌ Отмена", "sc:ads")]]))


async def _preview(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    product = await db.get_product(data["pid"])
    fake = {"media_kind": data["media_kind"], "file_id": data["file_id"], "text_html": data["html"],
            "buttons": data.get("buttons", [])}
    await bot.send_message(chat_id, "👁 <b>Так будет выглядеть пост:</b>", parse_mode="HTML")
    try:
        await send_ad(bot, fake, chat_id)
    except Exception as exc:
        await bot.send_message(chat_id, f"Не получилось показать пост: {esc(str(exc)[:200])}. Попробуй ещё раз.")
        return
    await bot.send_message(chat_id, f"Формат: <b>{esc(product['title'])}</b>\nЦена: <b>{product['price']:g} USDT</b>",
                           parse_mode="HTML", reply_markup=_kb([
                               [("📨 Отправить на проверку", "ao:send", "success")],
                               [("✏️ Заново", f"ao:n:{product['id']}"), ("❌ Отмена", "sc:ads")]]))


@router.message(Order.buttons, F.text)
async def on_buttons(message: Message, bot: Bot, state: FSMContext) -> None:
    rows, errors = parse_buttons(message.text)
    if errors or not rows:
        return await message.answer("Не разобрал:\n" + "\n".join(esc(e) for e in errors[:5]) + "\n\n" + BUTTONS_HINT,
                                    parse_mode="HTML")
    await state.update_data(buttons=rows)
    await _preview(bot, message.chat.id, state)


@router.callback_query(Order.buttons, F.data == "ao:nob")
async def cb_no_buttons(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.update_data(buttons=[])
    await cb.answer()
    await _preview(bot, cb.from_user.id, state)


@router.callback_query(Order.buttons, F.data == "ao:send")
async def cb_send(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    product = await db.get_product(data["pid"])
    user = cb.from_user
    name = full_name(user.first_name, user.last_name) + (f" @{user.username}" if user.username else "")
    oid = await db.create_order(user.id, name, product["kind"], product["title"], product["price"], product["days"],
                                data["media_kind"], data["file_id"], data["html"], data.get("buttons", []),
                                "moderation")
    await cb.answer()
    await cb.message.edit_text(f"📨 Заказ #{oid} отправлен на проверку. Как только модератор одобрит, "
                               "пришлю реквизиты для оплаты.")
    order = await db.get_order(oid)
    for owner in config.OWNER_IDS:
        try:
            await bot.send_message(owner, f"🧾 <b>Новый заказ рекламы #{oid}</b>\n\n"
                                          f"Формат: {esc(product['title'])}\nЦена: {product['price']:g} USDT\n"
                                          f"Заказчик: {esc(name)} (<code>{user.id}</code>)\n\nПост ниже 👇",
                                   parse_mode="HTML")
            await send_ad(bot, order, owner)
            await bot.send_message(owner, f"Решение по заказу #{oid}:", reply_markup=_kb([
                [("✅ Одобрить", f"ord:ok:{oid}", "success"), ("❌ Отклонить", f"ord:no:{oid}", "danger")],
                [("💵 Оплачено напрямую", f"ord:paid:{oid}")]]))
        except Exception:
            pass


@router.callback_query(F.data.startswith("ord:chk:"))
async def cb_check(cb: CallbackQuery, bot: Bot) -> None:
    oid = int(cb.data.split(":")[2])
    order = await db.get_order(oid)
    if not order or order["user_id"] != cb.from_user.id:
        return await cb.answer()
    if order["status"] != "awaiting":
        return await cb.answer("Этот заказ уже оплачен или закрыт", show_alert=True)
    await adorders.check_payments(bot, force=True)
    order = await db.get_order(oid)
    if order["status"] == "awaiting":
        await cb.answer("Пока не вижу платёж. Перевод обычно доходит за 1-3 минуты, проверю ещё сам.",
                        show_alert=True)
    else:
        await cb.answer("✅ Оплата найдена!")
