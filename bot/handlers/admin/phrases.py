"""Админка → Фразы и стикеры: база реплик бота по категориям. Это то, чем бот говорит без нейросети:
когда сам влезает фразой, когда в чате смеются или матерятся, приветствия, вопросы дня."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.handlers.admin.states import PhraseAdd
from bot.phrases_seed import CATS
from bot.textutil import esc, short

router = Router(name="admin-phrases")
PAGE = 10
KIND_NAMES = {"sticker": "Стикеры", "gif": "Гифки"}


def _kind(cat: str) -> str:
    return db.phrase_kind(cat)


async def _menu(target) -> None:
    n = await db.count_phrases()
    total = sum(v for k, v in n.items() if k not in ("sticker", "gif"))
    text = ("🗯 <b>Фразы и стикеры</b>\n\n"
            "Этим бот говорит без нейросети: сам влезает в разговор, реагирует на смех и мат, здоровается, "
            "задаёт вопрос дня. Чем больше фраз, тем живее бот и меньше расход.\n\n"
            f"Всего фраз: <b>{total}</b> · стикеров: <b>{n.get('sticker', 0)}</b> · гифок: <b>{n.get('gif', 0)}</b>\n\n"
            "Выбери категорию 👇")
    items = list(CATS.items())
    rows = [[(f"{name} · {n.get(_kind(cat), 0)}", f"ph:c:{cat}:0") for cat, (name, _) in items[i:i + 2]]
            for i in range(0, len(items), 2)]
    rows.append([(f"🖼 Стикеры · {n.get('sticker', 0)}", "ph:v:sticker:0"), (f"🎞 Гифки · {n.get('gif', 0)}", "ph:v:gif:0")])
    rows.append([("➕ Добавить стикеры и гифки", "ph:add:media")])
    await show(target, text, kb(rows + [[BACK_MENU]]))


@router.callback_query(F.data == "ph:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _menu(cb)


async def _cat(target, cat: str, page: int) -> None:
    name, purpose = CATS.get(cat, ("Фразы", ""))
    rows, total = await db.list_phrases(_kind(cat), page * PAGE, PAGE)
    if not rows and page > 0:
        page = 0
        rows, total = await db.list_phrases(_kind(cat), 0, PAGE)
    pages = max(1, (total + PAGE - 1) // PAGE)
    text = (f"<b>{name}</b> · {total}\n<i>{purpose}</i>\n\n"
            + ("\n".join(f"• {esc(short(r['content'], 90))}" for r in rows) if rows else "Пока пусто.")
            + f"\n\nСтр. {page + 1} из {pages}. Нажми на фразу внизу, чтобы удалить.")
    buttons = [[(f"🗑 {short(r['content'], 26)}", f"ph:d:{r['id']}:{cat}:{page}") for r in rows[i:i + 2]]
               for i in range(0, len(rows), 2)]
    nav = []
    if page > 0:
        nav.append(("◀️", f"ph:c:{cat}:{page - 1}"))
    if page + 1 < pages:
        nav.append(("▶️", f"ph:c:{cat}:{page + 1}"))
    await show(target, text, kb([[("➕ Добавить фразы", f"ph:add:{cat}", "success")]] + buttons
                                + [nav, [("⬅️ Категории", "ph:menu"), BACK_MENU]]))


@router.callback_query(F.data.startswith("ph:c:"))
async def cb_cat(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    _, _, cat, page = cb.data.split(":")
    await _cat(cb, cat, int(page))


@router.callback_query(F.data.startswith("ph:add:"))
async def cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    cat = cb.data.split(":")[2]
    await state.set_state(PhraseAdd.collecting)
    await state.update_data(cat=cat)
    if cat == "media":
        return await show(cb, "➕ <b>Стикеры и гифки</b>\n\nПрисылай стикеры и гифки подряд, сколько угодно. "
                              "Закончил, жми Готово.", kb([[("✅ Готово", "ph:menu")]]))
    name, purpose = CATS.get(cat, ("Фразы", ""))
    hint = "\n\n<code>{name}</code> в тексте заменится на имя человека." if cat in ("tag", "greet") else ""
    await show(cb, f"➕ <b>{name}</b>\n<i>{purpose}</i>\n\nПришли фразы: каждую с новой строки или через "
                   f"<code>;</code> в одну строку. Можно сразу много.{hint}\n\nЗакончил, жми Готово.",
               kb([[("✅ Готово", f"ph:c:{cat}:0")]]))


@router.message(PhraseAdd.collecting, F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    cat = (await state.get_data()).get("cat", "any")
    if cat == "media":
        return await message.answer("Сюда нужны стикеры или гифки. Фразы добавляются в своей категории.")
    if message.text.startswith("/"):
        return await message.answer("Это похоже на команду. Закончить: кнопка Готово или /cancel.")
    parts = []
    for line in message.text.splitlines():
        parts += line.split(";") if ";" in line else [line]
    parts = [" ".join(p.split())[:500] for p in parts]
    parts = [p for p in parts if p]
    added = 0
    for p in parts:
        added += await db.add_phrase(_kind(cat), p)
    skipped = len(parts) - added
    await message.answer(f"✅ Добавил: {added}" + (f" (повторов пропущено: {skipped})" if skipped else "")
                         + ". Можно прислать ещё.", reply_markup=kb([[("✅ Готово", f"ph:c:{cat}:0")]]))


@router.message(PhraseAdd.collecting, F.sticker)
async def on_sticker(message: Message) -> None:
    ok = await db.add_phrase("sticker", message.sticker.file_id)
    await message.answer("✅ Стикер добавлен" if ok else "Такой уже есть", reply_markup=kb([[("✅ Готово", "ph:menu")]]))


@router.message(PhraseAdd.collecting, F.animation)
async def on_gif(message: Message) -> None:
    ok = await db.add_phrase("gif", message.animation.file_id)
    await message.answer("✅ Гифка добавлена" if ok else "Такая уже есть", reply_markup=kb([[("✅ Готово", "ph:menu")]]))


@router.callback_query(F.data.startswith("ph:d:"))
async def cb_delete_text(cb: CallbackQuery) -> None:
    _, _, pid, cat, page = cb.data.split(":")
    await db.delete_phrase(int(pid))
    await cb.answer("🗑 Удалено")
    await _cat(cb, cat, int(page))


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
        return await cb.message.answer(f"{KIND_NAMES[kind]}: пока пусто.",
                                       reply_markup=kb([[("➕ Добавить", "ph:add:media")], [("⬅️ Назад", "ph:menu")]]))
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
