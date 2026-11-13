"""Супер-админка → Экраны и тексты: правка экранов лички без кода.
Текст (с премиум-эмодзи и форматированием), картинка, кнопки: название, цвет, эмодзи на кнопке,
куда ведёт, ряд, удаление и добавление."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db, screens
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.services import menu
from bot.textutil import esc, short

router = Router(name="admin-screens")

STYLES = ["", "primary", "success", "danger"]
STYLE_NAMES = {"": "обычная", "primary": "🔵 синяя", "success": "🟢 зелёная", "danger": "🔴 красная"}
ACTIONS = {"act:support": "🆘 Поддержка", "act:add_group": "➕ Добавить в чат", "act:donors": "👑 Топ донатеров",
           "act:rent": "💳 Оплатить аренду", "act:wl_pay": "💳 Оплатить свой бот"}


class Edit(StatesGroup):
    text = State()
    photo = State()
    btn_text = State()
    btn_new = State()
    btn_emoji = State()
    btn_url = State()


def action_name(action: str) -> str:
    if action.startswith("screen:"):
        return "экран «" + screens.TITLES.get(action[7:], action[7:]) + "»"
    if action.startswith("url:"):
        return "ссылка " + short(action[4:], 40)
    if action.startswith("act:support"):
        return "поддержка" + (f" ({action.split(':', 2)[2]})" if action.count(":") >= 2 else "")
    return ACTIONS.get(action, action)


async def _save(key: str, **changes) -> dict:
    screen = await menu.load(key)
    screen.update(changes)
    await db.save_screen(key, screen["text"], screen["photo"], screen["buttons"])
    return screen


@router.callback_query(F.data == "se:list")
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    rows = [[(f"📄 {title}", f"se:o:{key}")] for key, title in screens.TITLES.items()]
    await show(cb, "🎨 <b>Экраны и тексты</b>\n\nЭто то, что видят люди в личке с ботом. "
                   "Выбери экран, чтобы поменять текст, картинку или кнопки.", kb(rows + [[BACK_MENU]]))


async def _card(target, key: str) -> None:
    screen = await menu.load(key)
    edited = await db.get_screen(key) is not None
    text = (f"📄 <b>{esc(screens.TITLES.get(key, key))}</b>{' · изменён' if edited else ' · по умолчанию'}\n\n"
            f"<b>Текст:</b>\n<blockquote>{esc(short(screen['text'], 500))}</blockquote>\n"
            f"<b>Картинка:</b> {'есть' if screen['photo'] else 'нет'}\n"
            f"<b>Кнопок:</b> {len(screen['buttons'])}")
    await show(target, text, kb([
        [("👁 Показать как у людей", f"se:v:{key}", "primary")],
        [("✏️ Текст", f"se:t:{key}"), ("🖼 Картинка", f"se:p:{key}")],
        [("🔘 Кнопки", f"se:b:{key}")],
        [("↩️ Вернуть как было", f"se:r:{key}", "danger")] if edited else [],
        [("⬅️ Экраны", "se:list"), BACK_MENU],
    ]))


@router.callback_query(F.data.startswith("se:o:"))
async def cb_open(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _card(cb, cb.data[5:])


@router.callback_query(F.data.startswith("se:v:"))
async def cb_preview(cb: CallbackQuery, bot: Bot) -> None:
    key = cb.data[5:]
    text, photo, markup = await menu.render(bot, key, cb.from_user)
    await cb.answer()
    await menu.send_screen(bot, cb.from_user.id, text, photo, markup)
    await cb.message.answer("☝️ так видят этот экран люди", reply_markup=kb([[("⬅️ К экрану", f"se:o:{key}")]]))


@router.callback_query(F.data.startswith("se:r:"))
async def cb_reset(cb: CallbackQuery) -> None:
    key = cb.data[5:]
    await db.reset_screen(key)
    await cb.answer("Вернул текст и кнопки по умолчанию")
    await _card(cb, key)


# ---------- текст и картинка ----------

@router.callback_query(F.data.startswith("se:t:"))
async def cb_text(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data[5:]
    await state.set_state(Edit.text)
    await state.update_data(key=key)
    await show(cb, "✏️ <b>Новый текст экрана</b>\n\nПришли текст сообщением. Жирный, курсив, ссылки, спойлеры "
                   "и <b>премиум-эмодзи</b> сохранятся как есть (премиум-эмодзи видны людям, только если у "
                   "владельца бота есть Telegram Premium).\n\n"
                   "Подстановки: <code>{name}</code> имя человека, <code>{chats}</code> <code>{members}</code> "
                   "<code>{dm}</code> охват, <code>{bot}</code> юзернейм бота, "
                   "<code>{rent_price}</code> и <code>{wl_price}</code> цены аренды и своего бота.",
               kb([[("Отмена", f"se:o:{key}")]]))


@router.message(Edit.text, F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    key = (await state.get_data())["key"]
    if len(message.text) > 4000:
        return await message.answer("Слишком длинно, до 4000 символов.")
    await _save(key, text=message.html_text)
    await state.clear()
    await message.answer("✅ Текст сохранён")
    await _card(message, key)


@router.callback_query(F.data.startswith("se:p:"))
async def cb_photo(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data[5:]
    await state.set_state(Edit.photo)
    await state.update_data(key=key)
    await show(cb, "🖼 Пришли картинку для экрана. Чтобы убрать картинку, пришли «-».",
               kb([[("Отмена", f"se:o:{key}")]]))


@router.message(Edit.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    key = (await state.get_data())["key"]
    if message.photo:
        await _save(key, photo=message.photo[-1].file_id)
    elif (message.text or "").strip() == "-":
        await _save(key, photo="")
    else:
        return await message.answer("Нужна картинка (фото) или «-».")
    await state.clear()
    await message.answer("✅ Сохранил")
    await _card(message, key)


# ---------- кнопки ----------

async def _buttons(target, key: str) -> None:
    screen = await menu.load(key)
    rows = []
    for row in screens.rows(screen["buttons"]):
        for b in row:
            i = screen["buttons"].index(b)
            color = {"primary": "🔵", "success": "🟢", "danger": "🔴"}.get(b.get("style", ""), "⚪️")
            rows.append([(f"{color} ряд {b.get('row', 0)}: {short(b['text'], 28)}", f"se:bo:{key}:{i}")])
    extra = "\n\nКнопки форматов рекламы и товаров добавляются сами, их тут нет." if key in ("ads", "shop") else ""
    await show(target, f"🔘 <b>Кнопки экрана «{esc(screens.TITLES.get(key, key))}»</b>\n\n"
                       f"Кнопки с одинаковым номером ряда стоят рядом.{extra}",
               kb(rows + [[("➕ Добавить кнопку", f"se:ba:{key}", "success")], [("⬅️ К экрану", f"se:o:{key}")]]))


@router.callback_query(F.data.startswith("se:b:"))
async def cb_buttons(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _buttons(cb, cb.data[5:])


async def _button_card(target, key: str, i: int) -> None:
    screen = await menu.load(key)
    if i >= len(screen["buttons"]):
        return await _buttons(target, key)
    b = screen["buttons"][i]
    style = b.get("style", "")
    text = (f"🔘 <b>{esc(b['text'])}</b>\n\n"
            f"Ведёт на: {esc(action_name(b.get('action', '')))}\n"
            f"Цвет: {STYLE_NAMES.get(style, style)}\n"
            f"Эмодзи на кнопке: {'есть' if b.get('emoji') else 'нет'}\n"
            f"Ряд: {b.get('row', 0)}")
    base = f"{key}:{i}"
    await show(target, text, kb([
        [("✏️ Название", f"se:bt:{base}"), ("🎨 Цвет", f"se:bc:{base}", style or None)],
        [("✨ Эмодзи на кнопке", f"se:be:{base}"), ("🔗 Куда ведёт", f"se:bl:{base}")],
        [("⬆️ Ряд выше", f"se:bu:{base}"), ("⬇️ Ряд ниже", f"se:bd:{base}")],
        [("🗑 Удалить кнопку", f"se:bx:{base}", "danger")],
        [("⬅️ Кнопки", f"se:b:{key}")],
    ]))


def _parse(data: str) -> tuple[str, int]:
    parts = data.split(":")
    return parts[2], int(parts[3])


@router.callback_query(F.data.startswith("se:bo:"))
async def cb_button(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _button_card(cb, *_parse(cb.data))


async def _change(key: str, i: int, fn) -> None:
    screen = await menu.load(key)
    if i < len(screen["buttons"]):
        fn(screen["buttons"], i)
        await db.save_screen(key, screen["text"], screen["photo"], screen["buttons"])


@router.callback_query(F.data.startswith(("se:bc:", "se:bu:", "se:bd:", "se:bx:")))
async def cb_quick(cb: CallbackQuery) -> None:
    op = cb.data[3:5]
    key, i = _parse(cb.data)

    def apply(buttons: list, idx: int) -> None:
        b = buttons[idx]
        if op == "bc":
            cur = b.get("style", "")
            b["style"] = STYLES[(STYLES.index(cur) + 1) % len(STYLES)] if cur in STYLES else ""
        elif op == "bu":
            b["row"] = max(0, int(b.get("row", 0)) - 1)
        elif op == "bd":
            b["row"] = int(b.get("row", 0)) + 1
        elif op == "bx":
            buttons.pop(idx)

    await _change(key, i, apply)
    if op == "bx":
        await cb.answer("Кнопка удалена")
        return await _buttons(cb, key)
    await _button_card(cb, key, i)


@router.callback_query(F.data.startswith("se:bt:"))
async def cb_btn_text(cb: CallbackQuery, state: FSMContext) -> None:
    key, i = _parse(cb.data)
    await state.set_state(Edit.btn_text)
    await state.update_data(key=key, i=i)
    await show(cb, "✏️ Пришли новое название кнопки (обычные эмодзи можно, до 60 символов).",
               kb([[("Отмена", f"se:bo:{key}:{i}")]]))


@router.message(Edit.btn_text, F.text)
async def on_btn_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await _change(data["key"], data["i"], lambda bs, idx: bs[idx].update(text=message.text.strip()[:60]))
    await _button_card(message, data["key"], data["i"])


@router.callback_query(F.data.startswith("se:be:"))
async def cb_btn_emoji(cb: CallbackQuery, state: FSMContext) -> None:
    key, i = _parse(cb.data)
    await state.set_state(Edit.btn_emoji)
    await state.update_data(key=key, i=i)
    await show(cb, "✨ Пришли сообщение с одним <b>премиум-эмодзи</b>, оно встанет на кнопку перед текстом. "
                   "Работает, если у владельца бота есть Telegram Premium.\n\nУбрать эмодзи: пришли «-».",
               kb([[("Отмена", f"se:bo:{key}:{i}")]]))


@router.message(Edit.btn_emoji)
async def on_btn_emoji(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if (message.text or "").strip() == "-":
        emoji = ""
    else:
        found = [e.custom_emoji_id for e in (message.entities or []) if e.type == "custom_emoji"]
        if not found:
            return await message.answer("Не вижу премиум-эмодзи в сообщении. Пришли его или «-».")
        emoji = found[0]
    await state.clear()
    await _change(data["key"], data["i"], lambda bs, idx: bs[idx].update(emoji=emoji))
    await _button_card(message, data["key"], data["i"])


@router.callback_query(F.data.startswith("se:bl:"))
async def cb_btn_link(cb: CallbackQuery) -> None:
    key, i = _parse(cb.data)
    rows = [[(f"📄 {title}", f"se:bls:{key}:{i}:{k}")] for k, title in screens.TITLES.items() if k != key]
    rows += [[(title, f"se:bla:{key}:{i}:{a[4:]}")] for a, title in ACTIONS.items()]
    rows += [[("🔗 Внешняя ссылка", f"se:blu:{key}:{i}")], [("Отмена", f"se:bo:{key}:{i}")]]
    await show(cb, "🔗 Куда будет вести кнопка?", kb(rows))


@router.callback_query(F.data.startswith(("se:bls:", "se:bla:")))
async def cb_btn_link_set(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    key, i, target = parts[2], int(parts[3]), parts[4]
    action = ("screen:" if parts[1] == "bls" else "act:") + target
    await _change(key, i, lambda bs, idx: bs[idx].update(action=action))
    await _button_card(cb, key, i)


@router.callback_query(F.data.startswith("se:blu:"))
async def cb_btn_url(cb: CallbackQuery, state: FSMContext) -> None:
    key, i = _parse(cb.data)
    await state.set_state(Edit.btn_url)
    await state.update_data(key=key, i=i)
    await show(cb, "🔗 Пришли ссылку (https://... или t.me/...).", kb([[("Отмена", f"se:bo:{key}:{i}")]]))


@router.message(Edit.btn_url, F.text)
async def on_btn_url(message: Message, state: FSMContext) -> None:
    url = message.text.strip()
    if url.lower().startswith("t.me/"):
        url = "https://" + url
    if not url.lower().startswith(("https://", "http://", "tg://")):
        return await message.answer("Это не похоже на ссылку. Пришли https://... или t.me/...")
    data = await state.get_data()
    await state.clear()
    await _change(data["key"], data["i"], lambda bs, idx: bs[idx].update(action="url:" + url))
    await _button_card(message, data["key"], data["i"])


@router.callback_query(F.data.startswith("se:ba:"))
async def cb_btn_new(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data[6:]
    await state.set_state(Edit.btn_new)
    await state.update_data(key=key)
    await show(cb, "➕ Пришли название новой кнопки. Потом выберешь, куда она ведёт.",
               kb([[("Отмена", f"se:b:{key}")]]))


@router.message(Edit.btn_new, F.text)
async def on_btn_new(message: Message, state: FSMContext) -> None:
    key = (await state.get_data())["key"]
    await state.clear()
    screen = await menu.load(key)
    rows = [int(b.get("row", 0)) for b in screen["buttons"] if int(b.get("row", 0)) < 90]
    screen["buttons"].append(screens.btn(message.text.strip()[:60], "screen:start", (max(rows) + 1) if rows else 0))
    await db.save_screen(key, screen["text"], screen["photo"], screen["buttons"])
    await _button_card(message, key, len(screen["buttons"]) - 1)

