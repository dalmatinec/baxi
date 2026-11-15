"""Общее для админки: главное меню, клавиатуры, показ экранов."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from bot import ai, config, db
from bot.textutil import esc, short

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


MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
          "ноябрь", "декабрь"]


def month_start() -> float:
    from datetime import datetime
    now = datetime.now(config.TZ)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


async def month_money() -> dict:
    """Деньги за текущий месяц: аренда, свой бот, реклама (USDT) и звёзды."""
    out = {"rent": 0.0, "wl": 0.0, "ads": 0.0, "rent_n": 0, "ads_n": 0}
    for o in await db.paid_orders(month_start()):
        key = o["kind"] if o["kind"] in ("rent", "wl") else "ads"
        out[key] += o["price"]
        if key in ("rent", "ads"):
            out[key + "_n"] += 1
    out["stars"] = await db.stars_total(month_start())
    return out


async def waiting() -> dict:
    return {"apps": len(await db.pending_chats()), "support": await db.support_new_count(),
            "orders": len(await db.orders_by_status("moderation"))}


def _money(v: float) -> str:
    return f"{v:g}$"


async def menu_text() -> str:
    """Главная: сводка в цифрах и что ждёт ответа."""
    from datetime import datetime
    reach = await db.reach()
    money = await month_money()
    w = await waiting()
    month = MONTHS[datetime.now(config.TZ).month - 1].capitalize()
    lines = ["🕷 <b>Панель владельца</b>", "",
             f"💬 {reach['chats']} чат. · 👥 {await db.people_count()} чел. · 📨 {reach['dm']} в личке"]
    if ai.enabled():
        lines.append(f"🤖 ИИ сегодня: <b>${await db.spent_today():.2f}</b> из ${config.DAILY_LIMIT_USD:.2f}")
    else:
        lines.append("🤖 ИИ <b>выключен</b>: нет AI_API_KEY в .env")
    lines.append(f"💰 {month}: {_money(money['rent'])} аренда · {_money(money['ads'])} реклама"
                 + (f" · {_money(money['wl'])} свой бот" if money["wl"] else "") + f" · ⭐{money['stars']}")
    if config.IS_MAIN:
        from bot.services import license
        clients = license.clients()
        if clients:
            lines.append(f"💼 Клиентов: <b>{len(clients)}</b>")
    parts = []
    if w["apps"]:
        parts.append(f"{w['apps']} заявк{'а' if w['apps'] == 1 else 'и'}")
    if w["support"]:
        parts.append(f"{w['support']} обращ.")
    if w["orders"]:
        parts.append(f"{w['orders']} заказ на проверке")
    lines += ["", "🔔 <b>Ждут тебя:</b> " + " · ".join(parts) if parts else "✅ Сейчас ничего не ждёт ответа"]
    return "\n".join(lines)


async def menu_kb() -> InlineKeyboardMarkup:
    w = await waiting()
    return kb([
        [(f"🔔 Заявки · {w['apps']}" if w["apps"] else "🔔 Заявки", "ap:list", "success" if w["apps"] else None),
         (f"🆘 Поддержка · {w['support']}" if w["support"] else "🆘 Поддержка", "su:list",
          "primary" if w["support"] else None)],
        [("💬 Чаты", "ch:list"), ("👥 Люди", "ppl:menu")],
        [("💰 Деньги", "sec:money"),
         (f"📣 Реклама · {w['orders']}" if w["orders"] else "📣 Реклама", "sec:ads", "danger" if w["orders"] else None)],
        [("🎨 Меню и тексты", "se:list"), ("🗂 Фразы, стикеры", "ph:menu")],
        [("🤖 ИИ и расход", "spend"), ("⚙️ Настройки", "cfg:menu")],
        [("💼 Клиенты", "cl:list", "success")] if config.IS_MAIN else [],
    ])


SECTIONS = {
    "ads": ("📣 <b>Реклама</b>\n\nЗаказы от людей, цены, рассылки и приём оплаты.", [
        [("🧾 Заказы", "or:list", "primary"), ("🛍 Форматы и цены", "pr:list")],
        [("📢 Рассылка", "bc:new", "success"), ("🗓 Свои посты по расписанию", "ad:list")],
        [("💳 Оплата USDT", "pay:info")],
    ]),
    "money": ("", [
        [("🧾 Заказы", "or:list"), ("📅 Аренды", "rent:list")],
        [("⭐ Донаты", "dn:top"), ("👛 Кошельки", "pay:info")],
        [("🛒 Товары за звёзды", "sh:menu"), ("🧾 Платежи и возвраты", "sh:pay")],
        [("🪙 Монеты и питомцы: выдать, тесты", "eca:menu", "success")],
    ]),
    "look": ("🎨 <b>Оформление</b>\n\nТо, что люди видят в личке, и фразы бота в чатах.", [
        [("🎨 Экраны и тексты", "se:list", "primary"), ("🗯 Фразы и стикеры", "ph:menu")],
    ]),
}


async def money_text() -> str:
    from datetime import datetime
    m = await month_money()
    awaiting = await db.orders_by_status("awaiting")
    month = MONTHS[datetime.now(config.TZ).month - 1]
    lines = [f"💰 <b>Деньги · {month}</b>", "",
             f"📅 Аренда: {m['rent_n']} · <b>{_money(m['rent'])}</b>",
             f"📣 Реклама: {m['ads_n']} заказ. · <b>{_money(m['ads'])}</b>",
             f"💼 Свой бот: <b>{_money(m['wl'])}</b>",
             f"⭐ Звёзды: <b>{m['stars']} ⭐</b>"]
    if awaiting:
        lines += ["", f"⏳ Ждут оплаты: {len(awaiting)} заказ. на {_money(sum(o['price'] for o in awaiting))}"]
    return "\n".join(lines)


@router.callback_query(lambda c: c.data and c.data.startswith("sec:"))
async def cb_section(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    key = cb.data[4:]
    text, rows = SECTIONS.get(key, SECTIONS["ads"])
    if key == "money":
        text = await money_text()
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
    import time
    from bot.services.approval import until_text
    chats = sorted([c for c in await db.list_chats() if c["rent_until"]], key=lambda c: c["rent_until"])
    lines, rows = [], []
    for c in chats:
        soon = c["rent_until"] - time.time() < 3 * 86400
        kind = "пробный" if c["trial"] else "аренда"
        lines.append(f"{'🟡' if soon else '🟢'} {esc(c['title'][:30])} · {kind} до {until_text(c['rent_until'])}"
                     + (", <i>скоро конец</i>" if soon else ""))
        row = [(c["title"][:24] or str(c["chat_id"]), f"ch:o:{c['chat_id']}")]
        if soon and c["added_by"]:
            row.append(("🔔 напомнить", f"rent:rm:{c['chat_id']}", "primary"))
        rows.append(row)
    text = ("📅 <b>Аренды</b>\n\n" + "\n".join(lines)) if chats else \
        "📅 <b>Аренд пока нет</b>\n\nВключить аренду: Чаты → чат → Доступ и аренда."
    await show(cb, text, kb(rows + [[("⬅️ Деньги", "sec:money"), BACK_MENU]]))


@router.callback_query(lambda c: c.data and c.data.startswith("rent:rm:"))
async def cb_rent_remind(cb: CallbackQuery) -> None:
    from bot.services.approval import until_text
    chat = await db.get_chat(int(cb.data.split(":")[2]))
    if not chat or not chat["added_by"]:
        return await cb.answer("Не знаю, кому напомнить")
    kind = "Пробный период" if chat["trial"] else "Аренда бота"
    try:
        await cb.bot.send_message(
            chat["added_by"], f"📅 {kind} в чате <b>{esc(chat['title'])}</b> заканчивается "
                              f"{until_text(chat['rent_until'])}. Чтобы бот остался, продли аренду 👇",
            parse_mode="HTML", reply_markup=kb([[("💳 Продлить аренду", f"rt:{chat['chat_id']}", "success")]]))
        await cb.answer("🔔 Напомнил", show_alert=True)
    except Exception:
        await cb.answer("Не дошло: человек не запускал бота в личке. Напиши ему напрямую.", show_alert=True)


@router.callback_query(lambda c: c.data == "dn:top")
async def cb_donors(cb: CallbackQuery) -> None:
    from bot.handlers.stars import donors_text
    await show(cb, await donors_text(), kb([[("⬅️ Деньги", "sec:money"), BACK_MENU]]))


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
    today = rows[0] if rows and rows[0]["day"] == db.today() else None
    left = config.DAILY_LIMIT_USD - (today["usd"] if today else 0)
    peak = "сейчас час пика, всё ×2" if ai.is_peak() else "сейчас обычные цены"
    text = ("🤖 <b>ИИ и расход</b>\n\n"
            + (f"Модель: <code>{config.AI_MODEL}</code>\n" if config.IS_MAIN else "")
            + f"Лимит в сутки на все чаты: <b>${config.DAILY_LIMIT_USD:.2f}</b>, "
              f"до ${config.DAILY_LIMIT_USD * 30:.0f} в месяц\n"
            f"Сегодня осталось: <b>${max(0, left):.3f}</b>\n"
            f"За 30 дней: <b>${month:.3f}</b>\n\n"
            + ("\n".join(lines) if lines else "Пока ни одного запроса.")
            + f"\n\n💡 Считаю как в счёте сервиса: вход ${config.PRICE_IN:g}, из кэша ${config.PRICE_CACHE:g}, "
              f"ответ ${config.PRICE_OUT:g} за 1 млн токенов, в часы пика ×{config.PRICE_PEAK_X:g} ({peak}). "
              "Дни до обновления посчитаны по старым ценам, они завышены. Точная сумма: platform.deepseek.com → Usage.\n\n"
            "Когда лимит на сегодня кончается, бот до полуночи отвечает фразами из базы.\n\n"
            "<b>Изменить лимит в сутки:</b>")
    steps = [0.1, 0.15, 0.2, 0.3, 0.5, 1]
    row = [((f"✓ ${v:g}" if abs(v - config.DAILY_LIMIT_USD) < 1e-9 else f"${v:g}"), f"lim:{v}") for v in steps]
    await show(cb, text, kb([[("⏰ По часам", "spend:hour"), ("💬 По чатам", "spend:chat_id"), ("🧩 На что", "spend:kind")],
                             row[:3], row[3:], [("✏️ Своя сумма", "lim:own")], [BACK_MENU]]))


@router.callback_query(lambda c: c.data.startswith("spend:"))
async def cb_spend_split(cb: CallbackQuery) -> None:
    """Расход за сегодня: по часам, по чатам или по видам запросов."""
    by = cb.data.split(":", 1)[1]
    rows = await db.ai_breakdown(db.today(), by)
    total = sum(r["usd"] for r in rows) or 1e-9
    titles = {"hour": "⏰ По часам", "chat_id": "💬 По чатам", "kind": "🧩 На что уходит"}
    lines = []
    chats = {c["chat_id"]: c["title"] for c in await db.list_chats(active_only=False)} if by == "chat_id" else {}
    for r in rows:
        if by == "hour":
            name = f"{r['k']:02d}:00"
        elif by == "chat_id":
            name = esc(short(chats.get(r["k"]) or ("без чата" if not r["k"] else str(r["k"])), 28))
        else:
            name = ai.KINDS.get(r["k"], r["k"])
        bar = "▰" * max(1, round(8 * r["usd"] / total)) if r["usd"] else "▱"
        lines.append(f"{name}: <b>${r['usd']:.4f}</b> · {r['requests']} запр. {bar}")
    text = (f"🤖 <b>{titles.get(by, by)}, сегодня</b>\n\n" + ("\n".join(lines) if lines else "Сегодня запросов пока нет.")
            + f"\n\nВсего: <b>${sum(r['usd'] for r in rows):.4f}</b> · {sum(r['requests'] for r in rows)} запр.")
    await show(cb, text, kb([[("⏰ По часам", "spend:hour"), ("💬 По чатам", "spend:chat_id"), ("🧩 На что", "spend:kind")],
                             [("⬅️ Расход", "spend"), BACK_MENU]]))


class LimitEdit(StatesGroup):
    value = State()


@router.callback_query(lambda c: c.data == "lim:own")
async def cb_limit_own(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LimitEdit.value)
    await show(cb, "✏️ Пришли лимит в долларах в сутки, например <code>5</code> или <code>2.5</code>",
               kb([[("Отмена", "spend")]]))


@router.message(LimitEdit.value, F.text)
async def on_limit_own(message: Message, state: FSMContext) -> None:
    try:
        value = round(float(message.text.replace(",", ".").replace("$", "").strip()), 2)
        if not 0 < value <= 100:
            raise ValueError
    except ValueError:
        return await message.answer("Нужно число от 0.01 до 100, например 5")
    await state.clear()
    config.DAILY_LIMIT_USD = value
    await db.kv_set("daily_limit", str(value))
    await message.answer(f"✅ Лимит ${value:g} в сутки, примерно ${value * 30:.0f} в месяц максимум",
                         reply_markup=kb([[("🤖 ИИ и расход", "spend"), BACK_MENU]]))


@router.callback_query(lambda c: c.data and c.data.startswith("lim:") and c.data != "lim:own")
async def cb_limit(cb: CallbackQuery) -> None:
    value = float(cb.data[4:])
    config.DAILY_LIMIT_USD = value
    await db.kv_set("daily_limit", str(value))
    await cb.answer(f"Лимит ${value:g} в сутки")
    await cb_spend(cb)
