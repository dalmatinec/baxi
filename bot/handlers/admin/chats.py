"""Админка → Чаты: имя бота, характер, тема чата, частота реплик, переключатели."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.services import approval
from bot.handlers.admin.common import BACK_MENU, kb, onoff, pct, show
from bot.handlers.admin.states import ChatEdit
from bot.textutil import esc, short

router = Router(name="admin-chats")

FIELDS = {
    "bot_name": ("Имя бота", 40,
                 "Как бота зовут в этом чате. На это имя он и откликается."),
    "aliases": ("Доп. имена", 200,
                "Другие имена, на которые бот откликается, через запятую.\n"
                "Например: <code>маратик, мара, бро</code>\nЧтобы очистить, пришли «-»."),
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
           "results": "🌙 Итоги дня", "rep": "⭐ Репутация", "bday": "🎂 Дни рождения"}


def _chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def _next(values: list, current) -> object:
    for v in values:
        if v > current + 1e-9:
            return v
    return values[0]


async def _card(target, chat_id: int) -> None:
    c = await db.get_chat(chat_id)
    if c is None:
        return await show(target, "Чат не найден.", kb([[("⬅️ Чаты", "ch:list")]]))
    if not c["active"]:
        status = "\n⚠️ <b>Бота нет в этом чате</b> (удалили или вышел)\n"
    elif not c["approved"]:
        status = "\n⏳ <b>Ждёт одобрения</b>, бот в чате молчит\n"
    elif c["rent_until"]:
        status = f"\n📅 Аренда до <b>{approval.until_text(c['rent_until'])}</b>\n"
    else:
        status = "\n✅ Одобрен, без срока\n"
    text = (f"💬 <b>{esc(c['title'] or str(chat_id))}</b>{status}\n\n"
            f"<b>Имя:</b> {esc(c['bot_name'])}\n"
            f"<b>Доп. имена:</b> {esc(c['aliases']) or '—'}\n"
            f"<b>Характер:</b> {esc(short(c['persona'], 300))}\n"
            f"<b>Тема:</b> {esc(short(c['topic'], 200))}\n\n"
            f"🎯 <b>Шанс влезть</b> в чужой разговор: {pct(c['chance'])} от сообщений\n"
            f"🤖 <b>Из них через ИИ:</b> {pct(c['ai_share'])}, остальное фразы и стикеры\n"
            f"⏱ <b>Пауза</b> между такими влезаниями: {c['cooldown']} сек\n"
            f"🌙 <b>Итоги дня</b> в {c['results_hour']}:00\n"
            f"На обращения по имени и ответы на его сообщения бот отвечает всегда, через ИИ.")
    cid = chat_id
    await show(target, text, kb([
        [("✏️ Имя", f"ch:e:{cid}:bot_name"), ("🔤 Доп. имена", f"ch:e:{cid}:aliases")],
        [("🎭 Характер", f"ch:e:{cid}:persona"), ("📌 Тема", f"ch:e:{cid}:topic")],
        [(f"🎯 Шанс: {pct(c['chance'])}", f"ch:c:{cid}:chance"),
         (f"🤖 ИИ: {pct(c['ai_share'])}", f"ch:c:{cid}:ai_share")],
        [(f"⏱ Пауза: {c['cooldown']}с", f"ch:c:{cid}:cooldown"),
         (f"🌙 Итоги в {c['results_hour']}:00", f"ch:c:{cid}:results_hour")],
        *[[(f"{label} {onoff(c[f])}", f"ch:t:{cid}:{f}") for f, label in pair]
          for pair in _chunks(list(TOGGLES.items()), 2)],
        [("✅ Разрешить", f"ap:ok:{cid}")] if c["active"] and not c["approved"] else [],
        [("📅 Аренда +30 дней", f"ap:rent:{cid}"), ("♾ Без срока", f"ap:inf:{cid}")] if c["active"] else [],
        [("🧹 Стереть память чата", f"ch:wipe:{cid}"), ("🚪 Выйти из чата", f"ap:no:{cid}")],
        [("⬅️ Чаты", "ch:list"), BACK_MENU],
    ]))


@router.callback_query(F.data == "ch:list")
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    chats = await db.list_chats(active_only=False)
    if not chats:
        return await show(cb, "Чатов пока нет. Добавь бота в группу, и она появится здесь.",
                          kb([[BACK_MENU]]))
    rows = [[(("⚠️ " if not c["active"] else "⏳ " if not c["approved"] else "📅 " if c["rent_until"] else "")
              + short(c["title"] or str(c["chat_id"]), 40),
              f"ch:o:{c['chat_id']}")] for c in chats[:50]]
    await show(cb, "💬 <b>Чаты</b>\n\nВыбери чат, чтобы настроить бота в нём.", kb(rows + [[BACK_MENU]]))


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
    await _card(cb, int(cid))


@router.callback_query(F.data.startswith("ch:t:"))
async def cb_toggle(cb: CallbackQuery) -> None:
    _, _, cid, field = cb.data.split(":")
    chat = await db.get_chat(int(cid))
    if chat and field in TOGGLES:
        await db.update_chat(int(cid), **{field: 0 if chat[field] else 1})
    await _card(cb, int(cid))


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
    current = esc(chat[field]) if chat and chat[field] else "—"
    await show(cb, f"✏️ <b>{title}</b>\n\nСейчас: {current}\n\n{hint}\n\nПришли новое значение или /cancel.",
               kb([[("Отмена", f"ch:o:{cid}")]]))


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
    await _card(message, cid)


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
        await approval.leave(bot, chat_id, "всем пока, ухожу 👋")
        await cb.answer("🚪 Вышел из чата")
    await _card(cb, chat_id)
