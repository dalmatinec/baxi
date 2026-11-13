"""Общее для админки: главное меню, клавиатуры, показ экранов."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from bot import ai, config, db

router = Router(name="admin-common")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _button(item: tuple) -> InlineKeyboardButton:
    text, data = item[0], item[1]
    style = item[2] if len(item) > 2 and item[2] in ("primary", "success", "danger") else None
    if data.startswith(("http://", "https://", "tg://")):
        return InlineKeyboardButton(text=text, url=data, style=style)
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    """[[('текст', 'callback'), ('текст', 'callback', 'success'), ...], ...] → клавиатура.
    Третий элемент: цвет кнопки primary (синяя), success (зелёная), danger (красная)."""
    return InlineKeyboardMarkup(inline_keyboard=[[_button(item) for item in row] for row in rows if row])


BACK_MENU = ("🏠 Главная", "menu")


async def show(target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Callback: правим текущее сообщение. Не получается (это стикер, фото): шлём новое."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup,
                                           link_preview_options=NO_PREVIEW)
        except Exception as exc:
            if "message is not modified" not in str(exc):
                await target.message.answer(text, parse_mode="HTML", reply_markup=markup,
                                            link_preview_options=NO_PREVIEW)
        try:
            await target.answer()
        except Exception:
            pass  # на кнопку уже ответили раньше
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=markup, link_preview_options=NO_PREVIEW)


def onoff(v) -> str:
    return "✅" if v else "❌"


def pct(v: float) -> str:
    return f"{round(v * 100)}%"


async def menu_text() -> str:
    """Главная: сводка в цифрах, всё важное на одном экране."""
    chats = await db.list_chats()
    pending = await db.pending_chats()
    moderation = await db.orders_by_status("moderation")
    awaiting = await db.orders_by_status("awaiting")
    spent = await db.spent_today()
    from bot.services.daily import midnight_ts
    stars_today = await db.stars_total(midnight_ts())
    lines = ["🏠 <b>Главная</b>", "",
             f"💬 Чатов работает: <b>{len(chats)}</b>" + (f" · ⏳ заявок: <b>{len(pending)}</b>" if pending else ""),
             f"🧾 Заказы рекламы: на проверке <b>{len(moderation)}</b>, ждут оплату <b>{len(awaiting)}</b>",
             f"⭐ Звёзд сегодня: <b>{stars_today}</b>"]
    if ai.enabled():
        lines.append(f"🤖 ИИ сегодня: <b>${spent:.3f}</b> из ${config.DAILY_LIMIT_USD:.2f}")
    else:
        lines.append("🤖 ИИ <b>выключен</b>: нет AI_API_KEY в .env")
    if config.IS_MAIN:
        from bot.services import license
        clients = license.clients()
        if clients:
            lines.append(f"💼 Клиентов: <b>{len(clients)}</b>")
    return "\n".join(lines)


async def menu_kb() -> InlineKeyboardMarkup:
    pending = len(await db.pending_chats())
    moderation = len(await db.orders_by_status("moderation"))
    return kb([
        [("💬 Чаты", "ch:list", "primary"),
         (f"⏳ Заявки · {pending}", "ap:list", "danger") if pending else ("⏳ Заявки", "ap:list")],
        [(f"📣 Реклама · {moderation}" if moderation else "📣 Реклама", "sec:ads", "danger" if moderation else None),
         ("⭐ Монетизация", "sec:money")],
        [("🎨 Оформление", "sec:look"), ("🤖 ИИ", "spend")],
        [("💼 Клиенты", "cl:list", "success")] if config.IS_MAIN else [],
    ])


SECTIONS = {
    "ads": ("📣 <b>Реклама</b>\n\nЗаказы от людей, цены, рассылки и приём оплаты.", [
        [("🧾 Заказы", "or:list", "primary"), ("🛍 Форматы и цены", "pr:list")],
        [("📢 Рассылка", "bc:new", "success"), ("🗓 Свои посты по расписанию", "ad:list")],
        [("💳 Оплата USDT", "pay:info")],
    ]),
    "money": ("⭐ <b>Монетизация</b>\n\nМагазин за звёзды, платежи, донатеры и аренды.", [
        [("🛒 Товары и цены", "sh:menu", "primary"), ("🧾 Платежи и возвраты", "sh:pay")],
        [("👑 Топ донатеров", "dn:top"), ("📅 Аренды", "rent:list")],
    ]),
    "look": ("🎨 <b>Оформление</b>\n\nТо, что люди видят в личке, и фразы бота в чатах.", [
        [("🎨 Экраны и тексты", "se:list", "primary"), ("🗯 Фразы и стикеры", "ph:menu")],
    ]),
}


@router.callback_query(lambda c: c.data and c.data.startswith("sec:"))
async def cb_section(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, rows = SECTIONS.get(cb.data[4:], SECTIONS["ads"])
    await show(cb, text, kb(rows + [[BACK_MENU]]))


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message, await menu_text(), await menu_kb())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message, "Отменил.\n\n" + await menu_text(), await menu_kb())


@router.callback_query(lambda c: c.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, await menu_text(), await menu_kb())


@router.callback_query(lambda c: c.data == "ap:list")
async def cb_pending(cb: CallbackQuery) -> None:
    chats = await db.pending_chats()
    rows = [[(f"⏳ {c['title'][:40] or c['chat_id']}", f"ch:o:{c['chat_id']}")] for c in chats]
    text = ("⏳ <b>Заявки на подключение</b>\n\nЭти чаты добавили бота, он ждёт твоего решения." if chats
            else "⏳ <b>Заявок нет</b>\n\nКогда кто-то добавит бота в чат, заявка появится здесь и придёт тебе в личку.")
    await show(cb, text, kb(rows + [[BACK_MENU]]))


@router.callback_query(lambda c: c.data == "rent:list")
async def cb_rents(cb: CallbackQuery) -> None:
    from bot.services.approval import until_text
    chats = sorted([c for c in await db.list_chats() if c["rent_until"]], key=lambda c: c["rent_until"])
    rows = [[(f"📅 {c['title'][:28]} · до {until_text(c['rent_until'])}", f"ch:o:{c['chat_id']}")] for c in chats]
    text = "📅 <b>Аренды</b>, по дате окончания" if chats else "📅 <b>Аренд пока нет</b>\n\nВключить аренду: Чаты → чат → Доступ и аренда."
    await show(cb, text, kb(rows + [[("⬅️ Монетизация", "sec:money"), BACK_MENU]]))


@router.callback_query(lambda c: c.data == "dn:top")
async def cb_donors(cb: CallbackQuery) -> None:
    from bot.handlers.stars import donors_text
    await show(cb, await donors_text(), kb([[("⬅️ Монетизация", "sec:money"), BACK_MENU]]))


@router.callback_query(lambda c: c.data == "pay:info")
async def cb_pay_info(cb: CallbackQuery) -> None:
    def state(value: str) -> str:
        return f"✅ <code>{value[:6]}…{value[-4:]}</code>" if value else "❌ не указан"
    text = ("💳 <b>Приём оплаты рекламы в USDT</b>\n\n"
            f"💎 Сеть TON: {state(config.PAY_TON_ADDRESS)}\n"
            f"🔺 Сеть TRC20: {state(config.PAY_TRON_ADDRESS)}\n"
            f"Ключ toncenter: {'✅' if config.TONCENTER_API_KEY else 'нет, работает и без него'}\n"
            f"Ключ TronGrid: {'✅' if config.TRONGRID_API_KEY else 'нет, работает и без него'}\n\n"
            "Поменять адреса: на сервере <code>nano /opt/linkhub/.env</code>, строки PAY_TON_ADDRESS и "
            "PAY_TRON_ADDRESS, потом <code>systemctl restart linkhub</code>.\n\n"
            "Если адресов нет, после одобрения заказчик пишет в поддержку, а ты жмёшь Оплачено напрямую.")
    await show(cb, text, kb([[("⬅️ Реклама", "sec:ads"), BACK_MENU]]))


@router.callback_query(lambda c: c.data == "spend")
async def cb_spend(cb: CallbackQuery) -> None:
    rows = await db.spend_report(30)
    lines = [f"{r['day']}: ${r['usd']:.3f} · {r['requests']} запр." for r in rows[:7]]
    month = sum(r["usd"] for r in rows)
    text = ("🤖 <b>ИИ и расход</b>\n\n"
            f"Модель: <code>{config.AI_MODEL}</code>\n"
            f"Лимит в сутки: <b>${config.DAILY_LIMIT_USD:.2f}</b> (меняется в .env, DAILY_LIMIT_USD)\n"
            f"За 30 дней: <b>${month:.3f}</b>\n\n"
            + ("\n".join(lines) if lines else "Пока ни одного запроса.")
            + "\n\nКогда лимит на сегодня кончается, бот до полуночи отвечает фразами из базы.")
    await show(cb, text, kb([[BACK_MENU]]))
