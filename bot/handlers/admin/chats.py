"""Админка → Чаты: список, заявки, доступ и аренда, реклама в чате. Сами настройки бота (характер, частота,
фишки, правила, триггеры) открываются кнопкой «⚙️ Настроить бота» в том же меню, что у админов чатов."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot import config, db
from bot.services import approval
from bot.handlers.admin.common import BACK_MENU, kb, pct, show
from bot.textutil import esc, plural, short

router = Router(name="admin-chats")

def _status(c) -> str:
    if not c["active"]:
        return "⚠️ бота нет в чате (удалили или вышел)"
    if not c["approved"]:
        return "⏳ ждёт одобрения, бот молчит"
    if c["free"]:
        return "🆓 бесплатный тариф: без нейросети"
    if c["rent_until"]:
        kind = "🎁 пробный" if c["trial"] else "📅 аренда"
        return f"{kind} до {approval.until_text(c['rent_until'])}"
    return "✅ работает, без срока"


async def _card(target, chat_id: int) -> None:
    """Карточка чата: коротко о главном и разделы настроек."""
    c = await db.get_chat(chat_id)
    if c is None:
        return await show(target, "Чат не найден.", kb([[("⬅️ Чаты", "ch:list")]]))
    if not c["active"]:
        return await show(target, f"💬 <b>{esc(c['title'] or str(chat_id))}</b>\n{_status(c)}\n\n"
                                  "Бота в этом чате уже нет. Его можно убрать из списка вместе с историей "
                                  "и статистикой этого чата.",
                          kb([[("📦 Перенести всё в другой чат", f"mc:mv:{chat_id}", "primary")],
                              [("🗑 Убрать из списка", f"ch:del:{chat_id}", "danger")],
                              [("⬅️ Удалённые чаты", "ch:dead"), BACK_MENU]]))
    text = (f"💬 <b>{esc(c['title'] or str(chat_id))}</b>\n"
            f"{_status(c)}\n\n"
            f"🎭 Бот здесь: <b>{esc(c['bot_name'])}</b>, болтает {pct(c['chance'])}\n"
            f"👥 Участников: {c['members'] or '?'}\n"
            f"👤 Добавил: {approval.adder_html(c)}\n"
            f"📣 Реклама в чате: {'✅ идёт' if c['ads'] else '❌ выключена'}")
    cid = chat_id
    pending = c["active"] and not c["approved"]
    await show(target, text, kb([
        [("✅ Разрешить", f"ap:ok:{cid}", "success"), (f"🎁 Пробные {config.TRIAL_DAYS} дн", f"ap:trial:{cid}")]
        if pending else [],
        [("⚙️ Настроить бота в чате", f"mc:o:{cid}", "primary")] if not pending else [],
        [("📅 Доступ и аренда", f"ch:s:{cid}:rent"),
         (f"📣 Реклама: {'✅' if c['ads'] else '❌'}", f"ch:ads:{cid}")],
        [("🚫 Отказать", f"ap:no:{cid}", "danger")] if pending else [],
    ] + _contact(c) + [[("⬅️ Чаты", "ch:list"), BACK_MENU]]))


def _contact(c) -> list[list[tuple]]:
    """Связь с тем, кто добавил бота: через бота и напрямую по юзернейму."""
    if not c["added_by"]:
        return []
    row = [("✍️ Написать добавившему", f"sup:{c['added_by']}")]
    if c["added_username"]:
        row.append((f"💬 @{c['added_username']}", f"https://t.me/{c['added_username']}"))
    return [row]


async def _section(target, chat_id: int, sec: str = "rent") -> None:
    c = await db.get_chat(chat_id)
    if c is None:
        return await show(target, "Чат не найден.", kb([[("⬅️ Чаты", "ch:list")]]))
    cid = chat_id
    title = esc(c["title"] or str(chat_id))
    text = (f"📅 <b>Доступ и аренда</b> · {title}\n\nСейчас: {_status(c)}\n\n"
            "<i>Аренда: бот сам предупредит за 3 дня до конца (пробный период: за день) и выйдет, когда срок "
            "кончится.</i>")
    rows = [[("✅ Разрешить", f"ap:ok:{cid}", "success")] if c["active"] and not c["approved"] else [],
            [("📅 +30 дней", f"ap:rent:{cid}", "primary"), (f"🎁 Пробные {config.TRIAL_DAYS} дн", f"ap:trial:{cid}")]
            if c["active"] else [],
            [("♾ Без срока", f"ap:inf:{cid}"), ("🆓 На бесплатный", f"ap:free:{cid}")] if c["active"] else [],
            [("⬅️ К чату", f"ch:o:{cid}"), BACK_MENU],
            [("🚪 Вывести бота из чата", f"ch:bye:{cid}")] if c["active"] else []]
    await show(target, text, kb(rows))


@router.callback_query(F.data.startswith("ch:s:"))
async def cb_section(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    _, _, cid, sec = cb.data.split(":")
    await _section(cb, int(cid), sec)


@router.callback_query(F.data == "ch:list")
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _list(cb)


async def _list(cb: CallbackQuery) -> None:
    chats = [c for c in await db.list_chats(active_only=False) if c["active"]]
    dead = await db.inactive_chats()
    rows = [[(("⏳ " if not c["approved"] else "📅 " if c["rent_until"] else "")
              + short(c["title"] or str(c["chat_id"]), 40),
              f"ch:o:{c['chat_id']}")] for c in chats[:50]]
    rows.append([("🔍 Проверить чаты", "ch:scan")])
    if dead:
        rows.append([(f"🗑 Удалённые чаты ({len(dead)})", "ch:dead")])
    text = ("💬 <b>Чаты</b>\n\nВыбери чат, чтобы настроить бота в нём." if chats else
            "💬 <b>Чаты</b>\n\nРабочих чатов пока нет. Добавь бота в группу, и она появится здесь.")
    await show(cb, text + "\n\n<i>🔍 Проверить: найду чаты, которые удалили или откуда бота выгнали, "
                          "пока он был выключен.</i>", kb(rows + [[BACK_MENU]]))


@router.callback_query(F.data == "ch:scan")
async def cb_scan(cb: CallbackQuery) -> None:
    await cb.answer("Проверяю...")
    gone = []
    for c in await db.list_chats(active_only=False):
        if c["active"] and await approval.bot_present(cb.bot, c["chat_id"]) is False:
            await db.update_chat(c["chat_id"], active=0, approved=0, pending_since=0)
            gone.append(c["title"] or str(c["chat_id"]))
    text = (f"🔍 Нашёл {len(gone)} {plural(len(gone), ('чат', 'чата', 'чатов'))} без бота:\n" + "\n".join(f"• {esc(t)}" for t in gone[:30])
            if gone else "🔍 Все чаты на месте, бот есть в каждом.")
    await show(cb, text, kb([[("🗑 Удалённые чаты", "ch:dead")] if gone else [], [("⬅️ Чаты", "ch:list"), BACK_MENU]]))


@router.callback_query(F.data == "ch:dead")
async def cb_dead(cb: CallbackQuery) -> None:
    dead = await db.inactive_chats()
    if not dead:
        return await show(cb, "🗑 Удалённых чатов нет.", kb([[("⬅️ Чаты", "ch:list"), BACK_MENU]]))
    rows = [[("⚠️ " + short(c["title"] or str(c["chat_id"]), 40), f"ch:o:{c['chat_id']}")] for c in dead[:40]]
    await show(cb, f"🗑 <b>Удалённые чаты</b>: {len(dead)}\n\nЧаты, где бота больше нет: его выгнали, чат удалили "
                   "или ты сам его вывел. Можно убрать их из списка вместе с историей и статистикой. "
                   "Платежи и заказы останутся.",
               kb(rows + [[("🗑 Убрать все из списка", "ch:purge", "danger")], [("⬅️ Чаты", "ch:list"), BACK_MENU]]))


@router.callback_query(F.data == "ch:purge")
async def cb_purge(cb: CallbackQuery) -> None:
    dead = await db.inactive_chats()
    for c in dead:
        await db.delete_chat(c["chat_id"])
    await cb.answer(f"🗑 Убрал {len(dead)}")
    await _list(cb)


@router.callback_query(F.data.startswith("ch:del:"))
async def cb_delete(cb: CallbackQuery) -> None:
    chat_id = int(cb.data.split(":")[2])
    chat = await db.get_chat(chat_id)
    if chat and chat["active"]:
        return await cb.answer("Бот ещё в этом чате. Сначала выйди из него.", show_alert=True)
    await db.delete_chat(chat_id)
    await cb.answer("🗑 Убрал из списка")
    await cb_dead(cb)


@router.callback_query(F.data.startswith("ch:o:"))
async def cb_open(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _card(cb, int(cb.data.split(":")[2]))


@router.callback_query(F.data.startswith("ch:bye:"))
async def cb_bye(cb: CallbackQuery) -> None:
    """Выход из чата только с подтверждением: случайно нажать нельзя."""
    cid = int(cb.data.split(":")[2])
    chat = await db.get_chat(cid)
    if not chat:
        return await cb.answer("чат не найден")
    await show(cb, f"⚠️ <b>Вывести бота из чата {esc(chat['title'] or str(cid))}?</b>\n\n"
                   "Бот попрощается и выйдет. Вернуть его сможет только админ чата, добавив заново, "
                   "и чат снова придётся одобрить. Настройки и история сохранятся.",
               kb([[("Нет, оставить", f"ch:o:{cid}", "success")],
                   [("Да, вывести бота", f"ap:no:{cid}", "danger")]]))


@router.callback_query(F.data.startswith("ch:ads:"))
async def cb_ads(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[2])
    chat = await db.get_chat(cid)
    if chat:
        await db.update_chat(cid, ads=0 if chat["ads"] else 1)
    await _card(cb, cid)


# ---------- одобрение и аренда ----------

@router.callback_query(F.data.startswith("ap:"))
async def cb_approval(cb: CallbackQuery) -> None:
    _, action, cid = cb.data.split(":")
    chat_id = int(cid)
    chat = await db.get_chat(chat_id)
    if chat is None:
        return await cb.answer("чат не найден")
    bot = cb.bot
    if action == "ok":
        await approval.approve(bot, chat_id)
        await cb.answer("✅ Разрешил")
    elif action == "rent":
        await approval.approve(bot, chat_id, rent_days=approval.RENT_DAYS, announce=not chat["approved"])
        chat = await db.get_chat(chat_id)
        await cb.answer(f"📅 Аренда до {approval.until_text(chat['rent_until'])}")
    elif action == "free":
        await db.update_chat(chat_id, approved=1, pending_since=0, rent_until=0, trial=0, free=1)
        await cb.answer("🆓 Чат на бесплатном тарифе")
    elif action == "trial":
        await approval.approve(bot, chat_id, rent_days=config.TRIAL_DAYS, announce=not chat["approved"], trial=True)
        await db.update_chat(chat_id, trial_used=1)
        chat = await db.get_chat(chat_id)
        await cb.answer(f"🎁 Пробный период до {approval.until_text(chat['rent_until'])}")
    elif action == "inf":
        await db.update_chat(chat_id, rent_until=0, rent_warned=0, trial=0, free=0)
        await cb.answer("♾ Теперь без срока")
    elif action == "no":
        await approval.leave(bot, chat_id, "Хозяин попросил тебя уйти из этого чата.")
        await cb.answer("🚪 Вышел из чата")
        return await _card(cb, chat_id)
    await _section(cb, chat_id, "rent")
