"""Админка → Чаты: имя бота, характер, тема чата, частота реплик, переключатели."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.services import approval
from bot.handlers.admin.common import BACK_MENU, kb, pct, show
from bot.handlers.admin.states import ChatEdit
from bot.textutil import esc, plural, short

router = Router(name="admin-chats")

FIELDS = {
    "bot_name": ("Имя бота", 40,
                 "Как бота зовут в этом чате. На это имя он и откликается."),
    "aliases": ("Доп. имена", 200,
                "Другие имена, на которые бот откликается, через запятую.\n"
                "Например: <code>паучок, спайди, бро</code>\nЧтобы очистить, пришли «-»."),
    "persona": ("Характер", 1200,
                "Кто он и как общается. Пиши как описание человека, например:\n"
                "<i>25 лет, из Алматы, работает таксистом, любит футбол и шашлыки, "
                "дерзкий но добрый, постоянно подкалывает, отвечает коротко</i>"),
    "topic": ("Тема чата", 600,
              "О чём этот чат и что в нём принято. Например:\n"
              "<i>чат знакомств и общения Сатпаева, народ 18-30, болтают обо всём</i>"),
}

CYCLES = {
    "chance": [0.0, 0.02, 0.04, 0.07, 0.12, 0.2],
    "ai_share": [0.0, 0.3, 0.5, 0.7, 1.0],
    "cooldown": [30, 60, 90, 180, 300, 600],
    "results_hour": [20, 21, 22, 23],
}
TOGGLES = {"greet": "👋 Приветствия", "games": "🎲 Игры", "ads": "📣 Реклама", "pairpoll": "💘 Как вам пара",
           "results": "🌙 Итоги дня", "rep": "⭐ Репутация", "bday": "🎂 Дни рождения", "shop": "🛒 Магазин"}


def _chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def _next(values: list, current) -> object:
    for v in values:
        if v > current + 1e-9:
            return v
    return values[0]


def _status(c) -> str:
    if not c["active"]:
        return "⚠️ бота нет в чате (удалили или вышел)"
    if not c["approved"]:
        return "⏳ ждёт одобрения, бот молчит"
    if c["rent_until"]:
        return f"📅 аренда до {approval.until_text(c['rent_until'])}"
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
                          kb([[("🗑 Убрать из списка", f"ch:del:{chat_id}", "danger")],
                              [("⬅️ Удалённые чаты", "ch:dead"), BACK_MENU]]))
    on = sum(1 for f in TOGGLES if c[f])
    text = (f"💬 <b>{esc(c['title'] or str(chat_id))}</b>\n"
            f"{_status(c)}\n\n"
            f"🎭 Бот здесь: <b>{esc(c['bot_name'])}</b>\n"
            f"👥 Участников: {c['members'] or '?'}\n"
            f"👤 Добавил: {approval.adder_html(c)}\n"
            f"⚙️ Влезает в {pct(c['chance'])} разговоров, через ИИ {pct(c['ai_share'])}\n"
            f"🎲 Включено фишек: {on} из {len(TOGGLES)}\n\n"
            "Выбери, что настроить 👇")
    cid = chat_id
    await show(target, text, kb([
        [("✅ Разрешить работу", f"ap:ok:{cid}", "success")] if c["active"] and not c["approved"] else [],
        [("🎭 Личность", f"ch:s:{cid}:who", "primary"), ("⚙️ Поведение", f"ch:s:{cid}:act", "primary")],
        [("🎲 Фишки", f"ch:s:{cid}:fx", "primary"), ("📅 Доступ и аренда", f"ch:s:{cid}:rent", "primary")],
        [("🧹 Память", f"ch:wipe:{cid}"), ("🚪 Выйти из чата", f"ap:no:{cid}", "danger")],
    ] + _contact(c) + [[("⬅️ Чаты", "ch:list"), BACK_MENU]]))


def _contact(c) -> list[list[tuple]]:
    """Связь с тем, кто добавил бота: через бота и напрямую по юзернейму."""
    if not c["added_by"]:
        return []
    row = [("✍️ Написать добавившему", f"sup:{c['added_by']}")]
    if c["added_username"]:
        row.append((f"💬 @{c['added_username']}", f"https://t.me/{c['added_username']}"))
    return [row]


async def _section(target, chat_id: int, sec: str) -> None:
    c = await db.get_chat(chat_id)
    if c is None:
        return await show(target, "Чат не найден.", kb([[("⬅️ Чаты", "ch:list")]]))
    cid = chat_id
    back = [("⬅️ К чату", f"ch:o:{cid}"), BACK_MENU]
    title = esc(c["title"] or str(chat_id))
    if sec == "who":
        text = (f"🎭 <b>Личность бота</b> · {title}\n\n"
                f"<b>Имя:</b> {esc(c['bot_name'])}\n"
                f"<b>Ещё откликается на:</b> {esc(c['aliases']) or 'нет'}\n\n"
                f"<b>Характер:</b>\n<blockquote>{esc(short(c['persona'], 600))}</blockquote>\n"
                f"<b>Тема чата:</b>\n<blockquote>{esc(short(c['topic'], 400))}</blockquote>")
        rows = [[("✏️ Имя", f"ch:e:{cid}:bot_name"), ("🔤 Доп. имена", f"ch:e:{cid}:aliases")],
                [("🎭 Характер", f"ch:e:{cid}:persona"), ("📌 Тема", f"ch:e:{cid}:topic")], back]
    elif sec == "act":
        text = (f"⚙️ <b>Поведение</b> · {title}\n\n"
                f"🎯 <b>Шанс влезть</b> в чужой разговор: {pct(c['chance'])} сообщений\n"
                f"🤖 <b>Из них через ИИ:</b> {pct(c['ai_share'])}, остальное фразы и стикеры\n"
                f"⏱ <b>Пауза</b> между такими влезаниями: {c['cooldown']} сек\n"
                f"🌙 <b>Итоги дня</b> в {c['results_hour']}:00\n\n"
                "<i>Если бота зовут по имени или отвечают ему, он отвечает всегда. Нажимай на кнопку, "
                "значение меняется по кругу.</i>")
        rows = [[(f"🎯 Шанс: {pct(c['chance'])}", f"ch:c:{cid}:chance"),
                 (f"🤖 ИИ: {pct(c['ai_share'])}", f"ch:c:{cid}:ai_share")],
                [(f"⏱ Пауза: {c['cooldown']}с", f"ch:c:{cid}:cooldown"),
                 (f"🌙 Итоги: {c['results_hour']}:00", f"ch:c:{cid}:results_hour")], back]
    elif sec == "fx":
        text = f"🎲 <b>Фишки</b> · {title}\n\n🟢 включено · ⚪️ выключено. Нажми, чтобы переключить."
        rows = [[(f"{'🟢' if c[f] else '⚪️'} {label}", f"ch:t:{cid}:{f}", "success" if c[f] else None)
                 for f, label in pair] for pair in _chunks(list(TOGGLES.items()), 2)] + [back]
    else:
        text = (f"📅 <b>Доступ и аренда</b> · {title}\n\nСейчас: {_status(c)}\n\n"
                "<i>Аренда: бот сам предупредит за 3 дня до конца и выйдет, когда срок кончится.</i>")
        rows = [[("✅ Разрешить", f"ap:ok:{cid}", "success")] if c["active"] and not c["approved"] else [],
                [("📅 +30 дней", f"ap:rent:{cid}", "primary"), ("♾ Без срока", f"ap:inf:{cid}")]
                if c["active"] else [],
                [("🚪 Выйти из чата", f"ap:no:{cid}", "danger")], back]
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


@router.callback_query(F.data.startswith("ch:c:"))
async def cb_cycle(cb: CallbackQuery) -> None:
    _, _, cid, field = cb.data.split(":")
    chat = await db.get_chat(int(cid))
    if chat and field in CYCLES:
        await db.update_chat(int(cid), **{field: _next(CYCLES[field], chat[field])})
    await _section(cb, int(cid), "act")


@router.callback_query(F.data.startswith("ch:t:"))
async def cb_toggle(cb: CallbackQuery) -> None:
    _, _, cid, field = cb.data.split(":")
    chat = await db.get_chat(int(cid))
    if chat and field in TOGGLES:
        await db.update_chat(int(cid), **{field: 0 if chat[field] else 1})
    await _section(cb, int(cid), "fx")


@router.callback_query(F.data.startswith("ch:wipe:"))
async def cb_wipe(cb: CallbackQuery) -> None:
    cid = cb.data.split(":")[2]
    await show(cb, "🧹 Стереть историю сообщений и заметки о людях в этом чате? Настройки останутся.",
               kb([[("Да, стереть", f"ch:wipe!:{cid}"), ("Отмена", f"ch:o:{cid}")]]))


@router.callback_query(F.data.startswith("ch:wipe!:"))
async def cb_wipe_ok(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[2])
    await db.clear_memory(cid)
    await _card(cb, cid)


@router.callback_query(F.data.startswith("ch:e:"))
async def cb_edit(cb: CallbackQuery, state: FSMContext) -> None:
    _, _, cid, field = cb.data.split(":")
    if field not in FIELDS:
        return await cb.answer()
    chat = await db.get_chat(int(cid))
    title, _, hint = FIELDS[field]
    await state.set_state(ChatEdit.value)
    await state.update_data(chat_id=int(cid), field=field)
    current = esc(chat[field]) if chat and chat[field] else "пусто"
    await show(cb, f"✏️ <b>{title}</b>\n\nСейчас: {current}\n\n{hint}\n\nПришли новое значение или /cancel.",
               kb([[("Отмена", f"ch:s:{cid}:who")]]))


@router.message(ChatEdit.value, F.text)
async def on_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field, cid = data["field"], data["chat_id"]
    title, limit, _ = FIELDS[field]
    value = message.text.strip()
    if field == "aliases" and value == "-":
        value = ""
    if len(value) > limit:
        return await message.answer(f"Слишком длинно, максимум {limit} символов. Сократи и пришли ещё раз.")
    if field != "aliases" and not value:
        return await message.answer("Пустое значение не подойдёт, пришли текст.")
    await db.update_chat(cid, **{field: value})
    await state.clear()
    await message.answer(f"✅ {title}: сохранил.")
    await _section(message, cid, "who")


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
    elif action == "inf":
        await db.update_chat(chat_id, rent_until=0, rent_warned=0)
        await cb.answer("♾ Теперь без срока")
    elif action == "no":
        await approval.leave(bot, chat_id, "Хозяин попросил тебя уйти из этого чата.")
        await cb.answer("🚪 Вышел из чата")
        return await _card(cb, chat_id)
    await _section(cb, chat_id, "rent")
