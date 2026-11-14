"""Админка → Фразы и стикеры: база случайных реплик бота."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.handlers.admin.states import PhraseAdd
from bot.textutil import esc, short

router = Router(name="admin-phrases")
PAGE = 8
KIND_NAMES = {"text": "Фразы", "sticker": "Стикеры", "gif": "Гифки"}


async def _menu(target) -> None:
    n = await db.count_phrases()
    text = ("🗯 <b>Фразы и стикеры</b>\n\n"
            "Это то, чем бот влезает в разговор без нейросети (и когда лимит ИИ кончился).\n\n"
            f"💬 Фраз: <b>{n.get('text', 0)}</b>\n"
            f"🖼 Стикеров: <b>{n.get('sticker', 0)}</b>\n"
            f"🎞 Гифок: <b>{n.get('gif', 0)}</b>")
    await show(target, text, kb([
        [("➕ Добавить", "ph:add")],
        [("💬 Фразы", "ph:l:text:0"), ("🖼 Стикеры", "ph:v:sticker:0"), ("🎞 Гифки", "ph:v:gif:0")],
        [BACK_MENU],
    ]))


@router.callback_query(F.data == "ph:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _menu(cb)


@router.callback_query(F.data == "ph:add")
async def cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PhraseAdd.collecting)
    await show(cb, "➕ <b>Добавление</b>\n\nПрисылай:\n"
                   "• текст: каждая строка станет отдельной фразой\n"
                   "• стикеры\n• гифки\n\nСколько угодно подряд. Закончил, жми Готово.",
               kb([[("✅ Готово", "ph:menu")]]))


@router.message(PhraseAdd.collecting, F.text)
async def on_text(message: Message) -> None:
    if message.text.startswith("/"):
        return await message.answer("Это похоже на команду. Закончить добавление: кнопка Готово или /cancel.")
    lines = [" ".join(line.split()) for line in message.text.splitlines()]
    lines = [line[:500] for line in lines if line]
    added = 0
    for line in lines:
        added += await db.add_phrase("text", line)
    await message.answer(f"✅ Добавил фраз: {added}" + (f" (повторов пропущено: {len(lines) - added})"
                                                       if added < len(lines) else ""),
                         reply_markup=kb([[("✅ Готово", "ph:menu")]]))


@router.message(PhraseAdd.collecting, F.sticker)
async def on_sticker(message: Message) -> None:
    ok = await db.add_phrase("sticker", message.sticker.file_id)
    await message.answer("✅ Стикер добавлен" if ok else "Такой уже есть",
                         reply_markup=kb([[("✅ Готово", "ph:menu")]]))


@router.message(PhraseAdd.collecting, F.animation)
async def on_gif(message: Message) -> None:
    ok = await db.add_phrase("gif", message.animation.file_id)
    await message.answer("✅ Гифка добавлена" if ok else "Такая уже есть",
                         reply_markup=kb([[("✅ Готово", "ph:menu")]]))


@router.callback_query(F.data.startswith("ph:l:"))
async def cb_list(cb: CallbackQuery) -> None:
    await _list(cb, int(cb.data.split(":")[3]))


async def _list(cb: CallbackQuery, page: int) -> None:
    rows, total = await db.list_phrases("text", page * PAGE, PAGE)
    if not rows and page > 0:
        page = 0
        rows, total = await db.list_phrases("text", 0, PAGE)
    pages = max(1, (total + PAGE - 1) // PAGE)
    text = f"💬 <b>Фразы</b> ({total}), стр. {page + 1}/{pages}\n\nНажми на фразу, чтобы удалить.\n\n" + \
        "\n".join(f"• {esc(short(r['content'], 80))}" for r in rows)
    buttons = [[(f"🗑 {short(r['content'], 30)}", f"ph:d:{r['id']}:{page}")] for r in rows]
    nav = []
    if page > 0:
        nav.append(("◀️", f"ph:l:text:{page - 1}"))
    if page + 1 < pages:
        nav.append(("▶️", f"ph:l:text:{page + 1}"))
    await show(cb, text, kb(buttons + [nav, [("⬅️ Назад", "ph:menu")]]))


@router.callback_query(F.data.startswith("ph:d:"))
async def cb_delete_text(cb: CallbackQuery) -> None:
    _, _, pid, page = cb.data.split(":")
    await db.delete_phrase(int(pid))
    await _list(cb, int(page))


@router.callback_query(F.data.startswith("ph:v:"))
async def cb_view_media(cb: CallbackQuery) -> None:
    """Стикеры и гифки показываем по одному: смотришь и решаешь, удалить или дальше."""
    _, _, kind, idx = cb.data.split(":")
    await _view(cb, kind, int(idx))


async def _view(cb: CallbackQuery, kind: str, idx: int) -> None:
    rows, total = await db.list_phrases(kind, idx, 1)
    if not rows and idx > 0:
        idx = 0
        rows, total = await db.list_phrases(kind, 0, 1)
    await cb.answer()
    if not rows:
        return await cb.message.answer(f"{KIND_NAMES[kind]}: пока пусто. Добавь через ➕ Добавить.",
                                       reply_markup=kb([[("⬅️ Назад", "ph:menu")]]))
    item = rows[0]
    markup = kb([
        [("🗑 Удалить", f"ph:x:{kind}:{item['id']}:{idx}"),
         (f"▶️ Дальше ({idx + 1}/{total})", f"ph:v:{kind}:{(idx + 1) % total}")],
        [("⬅️ Назад", "ph:menu")],
    ])
    if kind == "sticker":
        await cb.message.answer_sticker(item["content"], reply_markup=markup)
    else:
        await cb.message.answer_animation(item["content"], reply_markup=markup)


@router.callback_query(F.data.startswith("ph:x:"))
async def cb_delete_media(cb: CallbackQuery) -> None:
    _, _, kind, pid, idx = cb.data.split(":")
    await db.delete_phrase(int(pid))
    try:
        await cb.message.delete()
    except Exception:
        pass
    await _view(cb, kind, int(idx))
