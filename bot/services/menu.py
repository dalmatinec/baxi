"""Показ экранов в личке: текст, картинка и кнопки из базы (или по умолчанию из bot/screens.py).
Разделы «Реклама» и «Магазин» добавляют к экрану свои кнопки через EXTRA_ROWS."""

import json
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from bot import config, db, screens
from bot.services.out import NO_PREVIEW
from bot.textutil import esc

log = logging.getLogger(__name__)

CURRENT_BOT: Bot | None = None  # нужен разделам, которые сами спрашивают Telegram (например «Мои чаты»)

# экран → функция, которая возвращает дополнительные ряды кнопок (форматы рекламы, товары магазина)
EXTRA_ROWS: dict[str, Callable[[User], Awaitable[list[list[InlineKeyboardButton]]]]] = {}
# кнопка с таким действием видна, только если функция вернула True (например «Мои чаты»)
SHOW_IF: dict[str, Callable[[User], Awaitable[bool]]] = {}


async def load(key: str) -> dict:
    row = await db.get_screen(key)
    if row:
        return {"text": row["text_html"], "photo": row["photo"], "buttons": json.loads(row["buttons"])}
    base = screens.defaults().get(key) or screens.defaults()["start"]
    return {"text": base["text"], "photo": "", "buttons": [dict(b) for b in base["buttons"]]}


def make_button(b: dict, bot_username: str) -> InlineKeyboardButton:
    action = b.get("action", "")
    kwargs = {"text": b.get("text") or "…"}
    if b.get("style") in ("primary", "success", "danger"):
        kwargs["style"] = b["style"]
    if b.get("emoji"):
        kwargs["icon_custom_emoji_id"] = b["emoji"]
    if action.startswith("screen:"):
        kwargs["callback_data"] = "sc:" + action[7:]
    elif action.startswith("url:"):
        kwargs["url"] = action[4:]
    elif action == "act:add_group":
        # сразу просим права админа, которые нужны боту: удалять, закреплять, приглашать
        kwargs["url"] = (f"https://t.me/{bot_username}?startgroup=true"
                         "&admin=delete_messages+pin_messages+invite_users")
    else:
        kwargs["callback_data"] = action[:64] or "sc:start"
    return InlineKeyboardButton(**kwargs)


async def render(bot: Bot, key: str, user: User | None) -> tuple[str, str, InlineKeyboardMarkup]:
    global CURRENT_BOT
    CURRENT_BOT = bot
    screen = await load(key)
    me = await bot.me()
    text = screen["text"]
    values = {"name": esc(user.first_name if user else ""), "bot": me.username or "",
              "botname": esc(config.DEFAULT_NAME or getattr(me, "first_name", "") or "")}
    if any(f"{{{k}}}" in text for k in ("chats", "members", "dm")):
        values.update({k: f"{v:,}".replace(",", " ") for k, v in (await db.reach()).items()})
    for key_, kind in (("rent_price", "rent"), ("wl_price", "wl")):
        if f"{{{key_}}}" in text:
            product = await db.product_by_kind(kind)
            values[key_] = f"{product['price']:g}" if product else "?"
    text = screens.fill(text, values)

    buttons = []
    for b in screen["buttons"]:
        check = SHOW_IF.get(b.get("action", ""))
        if check and not (user and await check(user)):
            continue
        buttons.append(b)
    screen["buttons"] = buttons
    button_rows = [[make_button(b, me.username or "") for b in row] for row in screens.rows(screen["buttons"])]
    extra = EXTRA_ROWS.get(key)
    if extra and user:
        added = await extra(user)
        # свои кнопки раздела ставим перед «В меню» и прочими нижними
        cut = len(button_rows)
        for i, row in enumerate(screens.rows(screen["buttons"])):
            if all(int(b.get("row", 0)) >= 90 for b in row):
                cut = i
                break
        button_rows = button_rows[:cut] + added + button_rows[cut:]
    if key == "start" and user and user.id in config.OWNER_IDS:
        button_rows.append([InlineKeyboardButton(text="⚙️ Админка", callback_data="menu")])
    return text, screen["photo"], InlineKeyboardMarkup(inline_keyboard=button_rows)


async def show(bot: Bot, target: Message | CallbackQuery, key: str) -> None:
    """Сообщение: отправляем экран. Кнопка: заменяем текущий экран (с картинкой: удаляем и шлём новый)."""
    user = target.from_user
    text, photo, markup = await render(bot, key, user)
    if isinstance(target, CallbackQuery):
        msg = target.message
        try:
            await target.answer()
        except Exception:
            pass
        if msg and not photo and not msg.photo:
            try:
                await msg.edit_text(text, parse_mode="HTML", reply_markup=markup, link_preview_options=NO_PREVIEW)
                return
            except Exception as exc:
                if "not modified" in str(exc):
                    return
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        chat_id = msg.chat.id if msg else user.id
    else:
        chat_id = target.chat.id
    await send_screen(bot, chat_id, text, photo, markup)


async def send_screen(bot: Bot, chat_id: int, text: str, photo: str, markup) -> None:
    if photo and len(text) <= 1024:
        await bot.send_photo(chat_id, photo, caption=text, parse_mode="HTML", reply_markup=markup)
        return
    if photo:
        await bot.send_photo(chat_id, photo)
    await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup, link_preview_options=NO_PREVIEW)
