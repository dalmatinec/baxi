"""Админка → Реклама: посты с кнопками, интервал, включение, отправка сейчас."""

import json

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.handlers.admin.common import BACK_MENU, kb, onoff, show
from bot.handlers.admin.states import AdEdit, AdNew
from bot.services import ads as ads_service
from bot.services.ads import extract_post
from bot.textutil import buttons_to_text, esc, parse_buttons, short

router = Router(name="admin-ads")

INTERVALS = [30, 60, 120, 180, 360, 720, 1440]
BUTTONS_HINT = (
    "Каждая строка — ряд кнопок, кнопки в одном ряду через <code>|</code>, "
    "цвет можно дописать в конце: зелёная, синяя или красная:\n\n"
    "<code>Общение 💬 - https://t.me/chat</code>\n"
    "<code>Найти ❤️ - https://t.me/bot - зелёная | Хочу 💋 - https://site.com - красная</code>"
)


def human_interval(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440} д"
    if minutes % 60 == 0:
        return f"{minutes // 60} ч"
    return f"{minutes} мин"


def _next_interval(current: int) -> int:
    return next((v for v in INTERVALS if v > current), INTERVALS[0])


def _title(message: Message, kind: str) -> str:
    plain = message.text or message.caption or ""
    if plain.strip():
        return short(plain, 40)
    return "Пост (" + {"photo": "фото", "video": "видео", "gif": "гифка"}.get(kind, "текст") + ")"


async def _card(target, ad_id: int) -> None:
    ad = await db.get_ad(ad_id)
    if ad is None:
        return await show(target, "Пост не найден.", kb([[("⬅️ Реклама", "ad:list")]]))
    buttons = json.loads(ad["buttons"])
    media = {"photo": "фото", "video": "видео", "gif": "гифка"}.get(ad["media_kind"], "только текст")
    chats = [c for c in await db.list_chats() if c["ads"]]
    text = (f"📣 <b>{esc(ad['title'])}</b>\n\n"
            f"Статус: {'▶️ включён' if ad['enabled'] else '⏸ на паузе'}\n"
            f"Медиа: {media}\n"
            f"Кнопок: {sum(len(r) for r in buttons)}\n"
            f"Интервал: каждые <b>{human_interval(ad['interval'])}</b>\n"
            f"Удалять прошлый пост перед новым: {onoff(ad['delete_prev'])}\n"
            f"Уходит в чатов: {len(chats)} (реклама выключается в настройках конкретного чата)")
    i = ad_id
    await show(target, text, kb([
        [("⏸ Пауза" if ad["enabled"] else "▶️ Включить", f"ad:t:{i}:enabled"),
         (f"⏱ {human_interval(ad['interval'])}", f"ad:i:{i}")],
        [(f"🗑 Удалять прошлый {onoff(ad['delete_prev'])}", f"ad:t:{i}:delete_prev")],
        [("📝 Заменить пост", f"ad:p:{i}"), ("🔘 Кнопки", f"ad:b:{i}")],
        [("👁 Предпросмотр", f"ad:v:{i}"), ("🚀 Отправить сейчас", f"ad:now:{i}")],
        [("❌ Удалить", f"ad:del:{i}")],
        [("⬅️ Реклама", "ad:list"), BACK_MENU],
    ]))


@router.callback_query(F.data == "ad:list")
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    items = await db.list_ads()
    rows = [[(("▶️ " if a["enabled"] else "⏸ ") + short(a["title"], 34), f"ad:o:{a['id']}")] for a in items]
    text = ("📣 <b>Реклама</b>\n\nПосты с кнопками, которые бот сам шлёт в чаты по расписанию."
            if items else "📣 <b>Реклама</b>\n\nПостов пока нет.")
    await show(cb, text, kb(rows + [[("➕ Новый пост", "ad:new")], [BACK_MENU]]))


@router.callback_query(F.data.startswith("ad:o:"))
async def cb_open(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _card(cb, int(cb.data.split(":")[2]))


# ---------- новый пост: пост → кнопки → интервал ----------

@router.callback_query(F.data == "ad:new")
async def cb_new(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdNew.post)
    await show(cb, "➕ <b>Новый пост, шаг 1 из 3</b>\n\nПришли пост: текст, фото, видео или гифку с подписью. "
                   "Жирный, ссылки и премиум-эмодзи сохранятся.", kb([[("Отмена", "ad:list")]]))


@router.message(AdNew.post)
async def on_new_post(message: Message, state: FSMContext) -> None:
    post = extract_post(message)
    if isinstance(post, str):
        return await message.answer(post)
    kind, file_id, html = post
    await state.update_data(kind=kind, file_id=file_id, html=html, title=_title(message, kind))
    await state.set_state(AdNew.buttons)
    await message.answer("🔘 <b>Шаг 2 из 3: кнопки</b>\n\n" + BUTTONS_HINT, parse_mode="HTML",
                         reply_markup=kb([[("Без кнопок", "ad:nobtn")], [("Отмена", "ad:list")]]))


async def _ask_interval(target, state: FSMContext) -> None:
    await state.set_state(AdNew.interval)
    rows = [[(human_interval(v), f"ad:ni:{v}") for v in INTERVALS[:4]],
            [(human_interval(v), f"ad:ni:{v}") for v in INTERVALS[4:]],
            [("Отмена", "ad:list")]]
    await show(target, "⏱ <b>Шаг 3 из 3</b>\n\nКак часто отправлять пост в каждый чат?", kb(rows))


@router.message(AdNew.buttons, F.text)
async def on_new_buttons(message: Message, state: FSMContext) -> None:
    rows, errors = parse_buttons(message.text)
    if errors or not rows:
        return await message.answer("Не разобрал:\n" + "\n".join(esc(e) for e in errors[:5]) +
                                    "\n\n" + BUTTONS_HINT, parse_mode="HTML")
    await state.update_data(buttons=rows)
    await _ask_interval(message, state)


@router.callback_query(AdNew.buttons, F.data == "ad:nobtn")
async def cb_no_buttons(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(buttons=[])
    await _ask_interval(cb, state)


@router.callback_query(AdNew.interval, F.data.startswith("ad:ni:"))
async def cb_new_interval(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    ad_id = await db.create_ad(data["title"], data["kind"], data["file_id"], data["html"],
                               data.get("buttons", []), int(cb.data.split(":")[2]))
    await cb.answer("Пост создан и включён")
    await _card(cb, ad_id)


# ---------- карточка поста ----------

@router.callback_query(F.data.startswith("ad:t:"))
async def cb_toggle(cb: CallbackQuery) -> None:
    _, _, ad_id, field = cb.data.split(":")
    ad = await db.get_ad(int(ad_id))
    if ad and field in ("enabled", "delete_prev"):
        await db.update_ad(int(ad_id), **{field: 0 if ad[field] else 1})
    await _card(cb, int(ad_id))


@router.callback_query(F.data.startswith("ad:i:"))
async def cb_interval(cb: CallbackQuery) -> None:
    ad_id = int(cb.data.split(":")[2])
    ad = await db.get_ad(ad_id)
    if ad:
        await db.update_ad(ad_id, interval=_next_interval(ad["interval"]))
    await _card(cb, ad_id)


@router.callback_query(F.data.startswith("ad:v:"))
async def cb_preview(cb: CallbackQuery, bot: Bot) -> None:
    ad = await db.get_ad(int(cb.data.split(":")[2]))
    if ad:
        try:
            await ads_service.send_ad(bot, ad, cb.from_user.id)
        except Exception as exc:
            return await cb.answer(f"Не отправилось: {str(exc)[:150]}", show_alert=True)
    await cb.answer()


@router.callback_query(F.data.startswith("ad:now:"))
async def cb_now(cb: CallbackQuery, bot: Bot) -> None:
    ad = await db.get_ad(int(cb.data.split(":")[2]))
    if not ad:
        return await cb.answer()
    await cb.answer("Отправляю…")
    sent = 0
    chats = [c for c in await db.list_chats() if c["ads"]]
    for chat in chats:
        sent += await ads_service.post_to_chat(bot, ad, chat["chat_id"])
    await cb.message.answer(f"🚀 Отправлено в {sent} из {len(chats)} чатов.")


@router.callback_query(F.data.startswith("ad:del:"))
async def cb_delete(cb: CallbackQuery) -> None:
    ad_id = cb.data.split(":")[2]
    await show(cb, "❌ Удалить этот пост насовсем?",
               kb([[("Да, удалить", f"ad:del!:{ad_id}"), ("Отмена", f"ad:o:{ad_id}")]]))


@router.callback_query(F.data.startswith("ad:del!:"))
async def cb_delete_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await db.delete_ad(int(cb.data.split(":")[2]))
    await cb_list(cb, state)


# ---------- замена поста и кнопок ----------

@router.callback_query(F.data.startswith("ad:p:"))
async def cb_edit_post(cb: CallbackQuery, state: FSMContext) -> None:
    ad_id = int(cb.data.split(":")[2])
    await state.set_state(AdEdit.post)
    await state.update_data(ad_id=ad_id)
    await show(cb, "📝 Пришли новый пост (текст, фото, видео или гифку). Кнопки останутся прежние.",
               kb([[("Отмена", f"ad:o:{ad_id}")]]))


@router.message(AdEdit.post)
async def on_edit_post(message: Message, state: FSMContext) -> None:
    post = extract_post(message)
    if isinstance(post, str):
        return await message.answer(post)
    kind, file_id, html = post
    ad_id = (await state.get_data())["ad_id"]
    await db.update_ad(ad_id, media_kind=kind, file_id=file_id, text_html=html, title=_title(message, kind))
    await state.clear()
    await message.answer("✅ Пост заменён.")
    await _card(message, ad_id)


@router.callback_query(F.data.startswith("ad:b:"))
async def cb_edit_buttons(cb: CallbackQuery, state: FSMContext) -> None:
    ad_id = int(cb.data.split(":")[2])
    ad = await db.get_ad(ad_id)
    await state.set_state(AdEdit.buttons)
    await state.update_data(ad_id=ad_id)
    current = buttons_to_text(json.loads(ad["buttons"])) if ad else ""
    await show(cb, "🔘 <b>Кнопки</b>\n\n" +
               (f"Сейчас:\n<code>{esc(current)}</code>\n\n" if current else "Сейчас кнопок нет.\n\n") +
               BUTTONS_HINT + "\n\nПришли новые кнопки или «-», чтобы убрать все.",
               kb([[("Отмена", f"ad:o:{ad_id}")]]))


@router.message(AdEdit.buttons, F.text)
async def on_edit_buttons(message: Message, state: FSMContext) -> None:
    ad_id = (await state.get_data())["ad_id"]
    if message.text.strip() == "-":
        rows = []
    else:
        rows, errors = parse_buttons(message.text)
        if errors or not rows:
            return await message.answer("Не разобрал:\n" + "\n".join(esc(e) for e in errors[:5]) +
                                        "\n\n" + BUTTONS_HINT, parse_mode="HTML")
    await db.update_ad(ad_id, buttons=rows)
    await state.clear()
    await message.answer("✅ Кнопки сохранены.")
    await _card(message, ad_id)
