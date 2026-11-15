"""Мастер настройки за 3 шага: характер, тема чата, частота. Запускается сразу после одобрения чата
кнопкой «⚙️ Настроить за минуту» и из раздела «Личность» (готовые характеры)."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db, presets
from bot.handlers.chatadmin import DENIED, _guard, _kb, _show, can_manage
from bot.textutil import esc, short

router = Router(name="chatwizard")

# шаг 3: три понятных варианта частоты, точнее можно выбрать потом в «Активности»
FREQ = [("🤫 Редко", 0.02), ("💬 Нормально", 0.05), ("🗣 Часто", 0.12)]


class Wizard(StatesGroup):
    persona = State()
    topic = State()


async def step1(target, cid: int) -> None:
    chat = await db.get_chat(cid)
    keys = list(presets.PERSONAS)
    rows = [[(presets.PERSONAS[k][0], f"wz:p:{cid}:{k}") for k in keys[i:i + 2]] for i in range(0, len(keys), 2)]
    rows += [[("✍️ Опишу сам", f"wz:p:{cid}:own")], [("⬅️ К чату", f"mc:o:{cid}")]]
    await _show(target, f"⚙️ <b>Настройка, шаг 1 из 3</b>\n\nКакой у меня характер в "
                        f"<b>{esc(chat['title'] or '')}</b>?\n\n<i>Готовый характер потом можно дописать "
                        "в разделе Личность.</i>", _kb(rows))


async def step2(target, cid: int, state: FSMContext) -> None:
    await state.set_state(Wizard.topic)
    await state.update_data(chat_id=cid)
    chat = await db.get_chat(cid)
    await _show(target, "⚙️ <b>Шаг 2 из 3</b>\n\nО чём ваш чат? Напиши парой слов, например:\n"
                        "<i>футбол, мемы, встречи по пятницам</i>\n\n"
                        f"Сейчас: {esc(short(chat['topic'], 200))}",
                _kb([[("Оставить как есть", f"wz:k:{cid}")]]))


async def step3(target, cid: int) -> None:
    chat = await db.get_chat(cid)
    rows = [[(f"✓ {label}" if abs(chat["chance"] - v) < 1e-6 else label, f"wz:f:{cid}:{i}",
              "primary" if abs(chat["chance"] - v) < 1e-6 else "") for i, (label, v) in enumerate(FREQ)]]
    await _show(target, "⚙️ <b>Шаг 3 из 3</b>\n\nКак часто мне самому влезать в разговор?\n\n"
                        "<i>Редко 2%, нормально 5%, часто 12% сообщений. Точнее, от 1% до 20%, можно выбрать "
                        "потом в разделе Активность. Если меня зовут, отвечаю всегда.</i>", _kb(rows))


async def done(target, cid: int) -> None:
    c = await db.get_chat(cid)
    label = next((lbl for lbl, v in FREQ if abs(c["chance"] - v) < 1e-6), presets.pct(c["chance"]))
    await _show(target, f"✅ <b>Готово!</b>\n\n🎭 {esc(c['bot_name'])}, {esc(short(c['persona'], 80))}\n"
                        f"📌 {esc(short(c['topic'], 80))}\n💬 болтаю: {label.split(' ', 1)[-1].lower()}\n\n"
                        "Всё можно поменять в любой момент: ⚙️ Мои чаты.",
                _kb([[("👀 Проверить, как я отвечаю", f"mc:try:{cid}", "primary")],
                     [("⚙️ Все настройки", f"mc:o:{cid}")]]))


@router.callback_query(F.data.startswith("wz:s:"))
async def cb_start(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await state.clear()
        await step1(cb, cid)


@router.callback_query(F.data.startswith("wz:p:"))
async def cb_persona(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    _, _, cid, key = cb.data.split(":")
    cid = int(cid)
    if not await _guard(cb, bot, cid):
        return
    if key == "own":
        await state.set_state(Wizard.persona)
        await state.update_data(chat_id=cid)
        return await _show(cb, "✍️ <b>Опиши мой характер</b>\n\n" + presets.FIELDS["persona"][2]
                           + "\n\nПришли описание сообщением, можно длинно (до 3000 символов).",
                           _kb([[("⬅️ Назад", f"wz:s:{cid}")]]))
    if key in presets.PERSONAS:
        await db.update_chat(cid, persona=presets.PERSONAS[key][1])
    await step2(cb, cid, state)


@router.message(Wizard.persona, F.text)
async def on_persona(message: Message, bot: Bot, state: FSMContext) -> None:
    cid = (await state.get_data())["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    text = message.text.strip()
    if len(text) < 10:
        return await message.answer("Слишком коротко, опиши хотя бы парой предложений.")
    await db.update_chat(cid, persona=text[:3000])
    await step2(message, cid, state)


@router.message(Wizard.topic, F.text)
async def on_topic(message: Message, bot: Bot, state: FSMContext) -> None:
    cid = (await state.get_data())["chat_id"]
    if not await can_manage(bot, message.from_user.id, cid):
        await state.clear()
        return await message.answer(DENIED)
    await db.update_chat(cid, topic=message.text.strip()[:1000])
    await state.clear()
    await step3(message, cid)


@router.callback_query(F.data.startswith("wz:k:"))
async def cb_keep_topic(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[2])
    if await _guard(cb, bot, cid):
        await state.clear()
        await step3(cb, cid)


@router.callback_query(F.data.startswith("wz:f:"))
async def cb_freq(cb: CallbackQuery, bot: Bot) -> None:
    _, _, cid, i = cb.data.split(":")
    cid = int(cid)
    if not await _guard(cb, bot, cid):
        return
    try:
        await db.update_chat(cid, chance=FREQ[int(i)][1])
    except (ValueError, IndexError):
        pass
    await done(cb, cid)
