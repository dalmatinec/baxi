"""«⚙️ Мои чаты»: создатели чатов и админы с правом назначать админов сами настраивают бота у себя.
Видят только свои чаты, где бот одобрен. Могут: имя, характер, тема, частота реплик, доля ИИ,
пауза, час итогов, фишки (кроме рекламы), стереть память. Остальное только у владельца бота."""

import time

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from bot import config, db
from bot.handlers.admin.chats import CYCLES, FIELDS, TOGGLES, _chunks, _next
from bot.services import menu
from bot.textutil import esc, short

router = Router(name="chatadmin")

# реклама остаётся у владельца бота
CLIENT_TOGGLES = {k: v for k, v in TOGGLES.items() if k != "ads"}
_rights: dict[tuple[int, int], tuple[float, bool]] = {}


DENIED = "Настраивать бота могут создатель чата и админы с правом назначать админов"


class McEdit(StatesGroup):
    value = State()


def _kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t, callback_data=d, style=s[0] if s and s[0] else None) for t, d, *s in row]
        for row in rows if row])


def pct(v: float) -> str:
    return f"{round(v * 100)}%"


async def can_manage(bot: Bot, user_id: int, chat_id: int) -> bool:
    """Владелец бота, создатель чата или админ с правом назначать админов, и бот в чате одобрен.
    Ответ Telegram кэшируем на 2 мин."""
    chat = await db.get_chat(chat_id)
    if not chat or not chat["active"] or not chat["approved"]:
        return False
    if user_id in config.OWNER_IDS:
        return True
    key = (chat_id, user_id)
    hit = _rights.get(key)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        ok = member.status == "creator" or (member.status == "administrator"
                                            and bool(getattr(member, "can_promote_members", False)))
    except Exception:
        ok = False
    _rights[key] = (time.time(), ok)
    return ok


async def my_chats(bot: Bot, user_id: int) -> list:
    return [c for c in await db.candidate_chats(user_id) if await can_manage(bot, user_id, c["chat_id"])]


async def start_rows(user: User) -> list[list[InlineKeyboardButton]]:
    """Кнопка в главном меню лички, только если у человека есть свои чаты с ботом."""
    bot = menu.CURRENT_BOT
    if bot and await my_chats(bot, user.id):
        return [[InlineKeyboardButton(text="⚙️ Мои чаты: настроить бота", callback_data="mc:list")]]
    return []


menu.EXTRA_ROWS["start"] = start_rows


async def _show(target: Message | CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    if isinstance(target, CallbackQuery):
        await target.answer()
        try:
            return await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception as exc:
            if "not modified" in str(exc):
                return
            target = target.message
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


async def show_list(bot: Bot, target: Message | CallbackQuery) -> None:
    chats = await my_chats(bot, target.from_user.id)
    if not chats:
        me = await bot.me()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить бота в чат", url=f"https://t.me/{me.username}?startgroup=true")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="sc:start")]])
        return await _show(target, "⚙️ <b>Мои чаты</b>\n\nЗдесь появятся чаты, где ты создатель или админ с правом "
                                   "назначать админов и где бот уже работает. "
                                   "Пока таких нет. Если только что добавил бота, дождись одобрения: "
                                   "я напишу сюда, когда всё готово.", kb)
    rows = [[(f"💬 {short(c['title'] or str(c['chat_id']), 40)}", f"mc:o:{c['chat_id']}")] for c in chats]
    await _show(target, "⚙️ <b>Мои чаты</b>\n\nВыбери чат, чтобы настроить бота в нём.",
                _kb(rows + [[("⬅️ В меню", "sc:start")]]))


@router.callback_query(F.data == "mc:list")
async def cb_list(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await show_list(bot, cb)


async def _guard(cb: CallbackQuery, bot: Bot, chat_id: int) -> bool:
    if await can_manage(bot, cb.from_user.id, chat_id):
        return True
    await cb.answer(DENIED, show_alert=True)
    return False


async def _card(target, chat_id: int) -> None:
    c = await db.get_chat(chat_id)
    on = sum(1 for f in CLIENT_TOGGLES if c[f])
    text = (f"⚙️ <b>{esc(c['title'] or str(chat_id))}</b>\n\n"
            f"🎭 Бот здесь: <b>{esc(c['bot_name'])}</b>\n"
            f"💬 Влезает в {pct(c['chance'])} разговоров, через ИИ {pct(c['ai_share'])}\n"
            f"🎲 Включено фишек: {on} из {len(CLIENT_TOGGLES)}\n\nЧто настроить? 👇")
    cid = chat_id
    await _show(target, text, _kb([
        [("🎭 Личность", f"mc:s:{cid}:who", "primary"), ("⚙️ Поведение", f"mc:s:{cid}:act", "primary")],
        [("🎲 Фишки", f"mc:s:{cid}:fx", "primary"), ("🧹 Стереть память", f"mc:w:{cid}")],
        [("🆘 Написать владельцу бота", f"mc:sup:{cid}")],
        [("⬅️ Мои чаты", "mc:list")]]))


async def _section(target, chat_id: int, sec: str) -> None:
    c = await db.get_chat(chat_id)
    cid = chat_id
    back = [("⬅️ К чату", f"mc:o:{cid}")]
    if sec == "who":
        text = (f"🎭 <b>Личность бота</b>\n\n<b>Имя:</b> {esc(c['bot_name'])}\n"
                f"<b>Ещё откликается на:</b> {esc(c['aliases']) or 'нет'}\n\n"
                f"<b>Характер:</b>\n<blockquote>{esc(short(c['persona'], 600))}</blockquote>\n"
                f"<b>Тема чата:</b>\n<blockquote>{esc(short(c['topic'], 400))}</blockquote>")
        rows = [[("✏️ Имя", f"mc:e:{cid}:bot_name"), ("🔤 Доп. имена", f"mc:e:{cid}:aliases")],
                [("🎭 Характер", f"mc:e:{cid}:persona"), ("📌 Тема", f"mc:e:{cid}:topic")], back]
    elif sec == "act":
        text = (f"⚙️ <b>Поведение</b>\n\n"
                f"🎯 <b>Шанс влезть</b> в чужой разговор: {pct(c['chance'])} сообщений\n"
                f"🤖 <b>Из них через ИИ:</b> {pct(c['ai_share'])}, остальное фразы и стикеры\n"
                f"⏱ <b>Пауза</b> между такими влезаниями: {c['cooldown']} сек\n"
                f"🌙 <b>Итоги дня</b> в {c['results_hour']}:00\n\n"
                "<i>Если бота зовут по имени или отвечают ему, он отвечает всегда. Нажимай на кнопку, "
                "значение меняется по кругу.</i>")
        rows = [[(f"🎯 Шанс: {pct(c['chance'])}", f"mc:c:{cid}:chance"),
                 (f"🤖 ИИ: {pct(c['ai_share'])}", f"mc:c:{cid}:ai_share")],
                [(f"⏱ Пауза: {c['cooldown']}с", f"mc:c:{cid}:cooldown"),
                 (f"🌙 Итоги: {c['results_hour']}:00", f"mc:c:{cid}:results_hour")], back]
    else:
        text = "🎲 <b>Фишки</b>\n\n🟢 включено · ⚪️ выключено. Нажми, чтобы переключить."
        rows = [[(f"{'🟢' if c[f] else '⚪️'} {label}", f"mc:t:{cid}:{f}", "success" if c[f] else "")
                 for f, label in pair] for pair in _chunks(list(CLIENT_TOGGLES.items()), 2)] + [back]
    await _show(target, text, _kb(rows))


@router.callback_query(F.data.startswith("mc:sup:"))
async def cb_support(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    """Админ чата пишет владельцу бота. Ответ придёт через обычную поддержку."""
    from bot.handlers.private import SupportWrite
    chat = await db.get_chat(int(cb.data.split(":")[2]))
    await state.set_state(SupportWrite.message)
    await state.update_data(topic=f"чат {chat['title']}" if chat else "чат")
    await menu.show(bot, cb, "support")


@router.callback_query(F.data.startswith("mc:o:"))
async def cb_open(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await _card(cb, cid)


@router.callback_query(F.data.startswith("mc:s:"))
async def cb_section(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    _, _, cid, sec = cb.data.split(":")
    if await _guard(cb, bot, int(cid)):
        await _section(cb, int(cid), sec)


@router.callback_query(F.data.startswith(("mc:c:", "mc:t:")))
async def cb_change(cb: CallbackQuery, bot: Bot) -> None:
    _, op, cid, field = cb.data.split(":")
    cid = int(cid)
    if not await _guard(cb, bot, cid):
        return
    chat = await db.get_chat(cid)
    if op == "c" and field in CYCLES:
        await db.update_chat(cid, **{field: _next(CYCLES[field], chat[field])})
        return await _section(cb, cid, "act")
    if op == "t" and field in CLIENT_TOGGLES:
        await db.update_chat(cid, **{field: 0 if chat[field] else 1})
    await _section(cb, cid, "fx")


@router.callback_query(F.data.startswith("mc:e:"))
async def cb_edit(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    _, _, cid, field = cb.data.split(":")
    if field not in FIELDS or not await _guard(cb, bot, int(cid)):
        return
    chat = await db.get_chat(int(cid))
    title, _, hint = FIELDS[field]
    await state.set_state(McEdit.value)
    await state.update_data(chat_id=int(cid), field=field)
    current = esc(chat[field]) if chat[field] else "пусто"
    await _show(cb, f"✏️ <b>{title}</b>\n\nСейчас: {current}\n\n{hint}\n\nПришли новое значение сообщением.",
                _kb([[("Отмена", f"mc:s:{cid}:who")]]))


@router.message(McEdit.value, F.text)
async def on_value(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    field, cid = data["field"], data["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
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


@router.callback_query(F.data.startswith("mc:w:"))
async def cb_wipe(cb: CallbackQuery, bot: Bot) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await _show(cb, "🧹 Стереть, что бот помнит о переписке и людях в этом чате? Настройки останутся.",
                    _kb([[("Да, стереть", f"mc:W:{cid}", "danger"), ("Отмена", f"mc:o:{cid}")]]))


@router.callback_query(F.data.startswith("mc:W:"))
async def cb_wipe_ok(cb: CallbackQuery, bot: Bot) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await db.clear_memory(cid)
        await _card(cb, cid)
