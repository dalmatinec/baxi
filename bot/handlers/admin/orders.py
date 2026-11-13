"""Супер-админка: заказы рекламы (одобрить, отклонить, отметить оплату), форматы и цены, рассылка."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.handlers.admin.ads import BUTTONS_HINT
from bot.handlers.admin.common import BACK_MENU, kb, onoff, show
from bot.services import adorders
from bot.services.ads import extract_post, send_ad
from bot.textutil import esc, parse_buttons, short

router = Router(name="admin-orders")

STATUS = {"moderation": "🕵️ на проверке", "awaiting": "⏳ ждёт оплату", "paid": "💸 оплачен",
          "running": "▶️ идёт", "done": "✅ выполнен", "rejected": "❌ отклонён", "expired": "⌛ не оплачен"}
DAYS = [1, 2, 3, 5, 7, 14]


class PriceEdit(StatesGroup):
    price = State()
    title = State()


class Broadcast(StatesGroup):
    post = State()
    buttons = State()


# ---------- заказы ----------

@router.callback_query(F.data == "or:list")
async def cb_orders(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    items = await db.orders_by_status(*STATUS, limit=20)
    items = [o for o in items if o["price"]]  # свои рассылки не показываем
    rows = [[(f"#{o['id']} {STATUS.get(o['status'], o['status'])} · {short(o['title'], 22)}", f"or:o:{o['id']}")]
            for o in items]
    await show(cb, "🧾 <b>Заказы рекламы</b> (последние 20)" if items else "🧾 Заказов пока нет.",
               kb(rows + [[BACK_MENU]]))


async def _order_card(target, oid: int) -> None:
    o = await db.get_order(oid)
    if not o:
        return await show(target, "Заказ не найден", kb([[("⬅️ Заказы", "or:list")]]))
    text = (f"🧾 <b>Заказ #{oid}</b> · {STATUS.get(o['status'], o['status'])}\n\n"
            f"Формат: {esc(o['title'])}\nЦена: {o['price']:g} USDT\n"
            + (f"К оплате: <code>{adorders.usdt(o['amount'])}</code> USDT\n" if o["amount"] else "")
            + f"Заказчик: {esc(o['user_name'])} (<code>{o['user_id']}</code>)\n"
            + (f"Результат: {esc(o['result'])}\n" if o["result"] else "")
            + (f"Транзакция: <code>{esc(short(o['tx'], 40))}</code>\n" if o["tx"] else ""))
    rows = [[("👁 Пост", f"or:v:{oid}")]]
    if o["status"] == "moderation":
        rows.append([("✅ Одобрить", f"ord:ok:{oid}", "success"), ("❌ Отклонить", f"ord:no:{oid}", "danger")])
    if o["status"] in ("moderation", "awaiting", "expired"):
        rows.append([("💵 Оплачено напрямую", f"ord:paid:{oid}")])
    rows.append([("⬅️ Заказы", "or:list"), BACK_MENU])
    await show(target, text, kb(rows))


@router.callback_query(F.data.startswith("or:o:"))
async def cb_order(cb: CallbackQuery) -> None:
    await _order_card(cb, int(cb.data.split(":")[2]))


@router.callback_query(F.data.startswith("or:v:"))
async def cb_order_post(cb: CallbackQuery, bot: Bot) -> None:
    order = await db.get_order(int(cb.data.split(":")[2]))
    await cb.answer()
    if order:
        await send_ad(bot, order, cb.from_user.id)


@router.callback_query(F.data.regexp(r"^ord:(ok|no|paid):\d+$"))
async def cb_decide(cb: CallbackQuery, bot: Bot) -> None:
    _, action, oid = cb.data.split(":")
    oid = int(oid)
    order = await db.get_order(oid)
    if not order:
        return await cb.answer("Заказ не найден")
    if action == "ok":
        if order["status"] != "moderation":
            return await cb.answer("Уже решено")
        await adorders.approve(bot, oid)
        await cb.answer("✅ Одобрен, заказчику ушли реквизиты")
    elif action == "no":
        if order["status"] != "moderation":
            return await cb.answer("Уже решено")
        await db.update_order(oid, status="rejected")
        try:
            await bot.send_message(order["user_id"], f"❌ Заказ #{oid} не прошёл проверку. "
                                                     "Подробности можно узнать в поддержке.")
        except Exception:
            pass
        await cb.answer("❌ Отклонён")
    elif action == "paid":
        await adorders.mark_paid(bot, oid, "manual")
        await cb.answer("💵 Отмечен оплаченным, запускаю")
    await _order_card(cb, oid)


# ---------- форматы и цены ----------

@router.callback_query(F.data == "pr:list")
async def cb_products(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await db.seed_products(adorders.DEFAULT_PRODUCTS)
    rows = [[(f"{'' if p['enabled'] else '⏸ '}{short(p['title'], 30)} · ${p['price']:g}", f"pr:o:{p['id']}")]
            for p in await db.products(enabled_only=False)]
    await show(cb, "🛍 <b>Форматы и цены рекламы</b>\n\nТак их видят люди в личке → Реклама.", kb(rows + [[BACK_MENU]]))


async def _product_card(target, pid: int) -> None:
    p = await db.get_product(pid)
    if not p:
        return
    await show(target, f"🛍 <b>{esc(p['title'])}</b>\n\nЧто это: {adorders.KIND_TEXT.get(p['kind'], p['kind'])}\n"
                       f"Цена: <b>{p['price']:g} USDT</b>\nДней подряд: {p['days']}\nПоказывается: {onoff(p['enabled'])}",
               kb([[("💵 Цена", f"pr:pr:{pid}"), ("✏️ Название", f"pr:ti:{pid}")],
                   [(f"📅 Дней: {p['days']}", f"pr:d:{pid}")] if p["kind"] == "groups" else [],
                   [("⏸ Скрыть" if p["enabled"] else "▶️ Показывать", f"pr:e:{pid}")],
                   [("⬅️ Форматы", "pr:list")]]))


@router.callback_query(F.data.startswith("pr:o:"))
async def cb_product(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _product_card(cb, int(cb.data.split(":")[2]))


@router.callback_query(F.data.startswith(("pr:d:", "pr:e:")))
async def cb_product_quick(cb: CallbackQuery) -> None:
    pid = int(cb.data.split(":")[2])
    p = await db.get_product(pid)
    if p and cb.data.startswith("pr:d:"):
        await db.update_product(pid, days=next((d for d in DAYS if d > p["days"]), DAYS[0]))
    elif p:
        await db.update_product(pid, enabled=0 if p["enabled"] else 1)
    await _product_card(cb, pid)


@router.callback_query(F.data.startswith(("pr:pr:", "pr:ti:")))
async def cb_product_edit(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[2])
    is_price = cb.data.startswith("pr:pr:")
    await state.set_state(PriceEdit.price if is_price else PriceEdit.title)
    await state.update_data(pid=pid)
    await show(cb, "💵 Пришли новую цену в USDT, например 12.5" if is_price else "✏️ Пришли новое название формата",
               kb([[("Отмена", f"pr:o:{pid}")]]))


@router.message(PriceEdit.price, F.text)
async def on_price(message: Message, state: FSMContext) -> None:
    try:
        price = round(float(message.text.replace(",", ".").strip()), 2)
        assert 0 < price < 100000
    except (ValueError, AssertionError):
        return await message.answer("Нужно число больше нуля, например 12.5")
    pid = (await state.get_data())["pid"]
    await state.clear()
    await db.update_product(pid, price=price)
    await _product_card(message, pid)


@router.message(PriceEdit.title, F.text)
async def on_title(message: Message, state: FSMContext) -> None:
    pid = (await state.get_data())["pid"]
    await state.clear()
    await db.update_product(pid, title=message.text.strip()[:60])
    await _product_card(message, pid)


# ---------- рассылка ----------

TARGETS = {"dm": "👤 в личку бота", "groups": "👥 по группам", "both": "🌐 везде"}


@router.callback_query(F.data == "bc:new")
async def cb_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    reach = await db.reach()
    await show(cb, f"📢 <b>Рассылка</b>\n\nВ личке: {reach['dm']} человек\nГрупп: {reach['chats']} "
                   f"({reach['members']} участников)\n\nКуда отправить?",
               kb([[("👤 В личку", "bc:t:dm"), ("👥 По группам", "bc:t:groups")],
                   [("🌐 Везде", "bc:t:both", "primary")], [BACK_MENU]]))


@router.callback_query(F.data.startswith("bc:t:"))
async def cb_broadcast_target(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.post)
    await state.update_data(target=cb.data[5:])
    await show(cb, "📝 Пришли пост: текст, фото, видео или гифку. Премиум-эмодзи и форматирование сохранятся.",
               kb([[("Отмена", "bc:new")]]))


@router.message(Broadcast.post)
async def on_broadcast_post(message: Message, state: FSMContext) -> None:
    post = extract_post(message)
    if isinstance(post, str):
        return await message.answer(post)
    await state.update_data(media_kind=post[0], file_id=post[1], html=post[2])
    await state.set_state(Broadcast.buttons)
    await message.answer("🔘 Кнопки?\n\n" + BUTTONS_HINT, parse_mode="HTML",
                         reply_markup=kb([[("Без кнопок", "bc:nob")], [("Отмена", "bc:new")]]))


async def _broadcast_preview(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    fake = {"media_kind": data["media_kind"], "file_id": data["file_id"], "text_html": data["html"],
            "buttons": data.get("buttons", [])}
    await send_ad(bot, fake, chat_id)
    await bot.send_message(chat_id, f"☝️ Предпросмотр. Отправить {TARGETS[data['target']]}?",
                           reply_markup=kb([[("🚀 Отправить", "bc:go", "success"), ("Отмена", "bc:new")]]))


@router.message(Broadcast.buttons, F.text)
async def on_broadcast_buttons(message: Message, bot: Bot, state: FSMContext) -> None:
    rows, errors = parse_buttons(message.text)
    if errors or not rows:
        return await message.answer("Не разобрал:\n" + "\n".join(esc(e) for e in errors[:5]))
    await state.update_data(buttons=rows)
    await _broadcast_preview(bot, message.chat.id, state)


@router.callback_query(Broadcast.buttons, F.data == "bc:nob")
async def cb_broadcast_nob(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.update_data(buttons=[])
    await cb.answer()
    await _broadcast_preview(bot, cb.from_user.id, state)


@router.callback_query(Broadcast.buttons, F.data == "bc:go")
async def cb_broadcast_go(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    oid = await db.create_order(cb.from_user.id, "владелец", data["target"], f"Рассылка {TARGETS[data['target']]}",
                                0, 1, data["media_kind"], data["file_id"], data["html"], data.get("buttons", []),
                                "paid")
    adorders.spawn(adorders.run_order(bot, await db.get_order(oid)))
    await cb.answer()
    await cb.message.edit_text(f"🚀 Рассылка #{oid} запущена. Когда закончу, напишу итог.")
