"""Личка с ботом для всех: меню-экраны, поддержка. Админка владельца живёт в handlers/admin."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import config, db
from bot.services import menu
from bot.textutil import esc, full_name

log = logging.getLogger(__name__)
router = Router(name="private")
router.message.filter(F.chat.type == "private")

START_PAYLOADS = {"rent": "add", "ads": "ads", "wl": "wl", "shop": "shop", "help": "help"}


class SupportWrite(StatesGroup):
    message = State()


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext, command: CommandObject) -> None:
    await state.clear()
    args = (command.args or "").strip()
    if args == "order":
        await state.set_state(SupportWrite.message)
        await state.update_data(topic="заказ проекта")
        return await message.answer("💼 <b>Заказать проект</b>\n\nОпиши одним сообщением, что хочешь: бот, сайт, "
                                    "мини-приложение или автоматизацию. Можно с примерами и сроками. "
                                    "Отвечу сюда же.", parse_mode="HTML")
    if args == "nick":  # купил ник в чате: сразу экран настройки
        from bot.handlers.stars import look_screen
        return await look_screen(message, message.from_user)
    if args == "mychats":
        from bot.handlers.chatadmin import show_list
        return await show_list(bot, message)
    if args.startswith("mc") and args[2:].lstrip("-").isdigit():
        from bot.handlers.chatadmin import can_manage, card, show_list
        cid = int(args[2:])
        if await can_manage(bot, message.from_user.id, cid):
            return await card(message, cid, message.from_user.id)
        return await show_list(bot, message)
    key = START_PAYLOADS.get((command.args or "").strip(), "start")
    await menu.show(bot, message, key)


@router.callback_query(F.data.startswith("sc:"))
async def cb_screen(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await menu.show(bot, cb, cb.data[3:])


@router.callback_query(F.data.startswith("act:support"))
async def cb_support(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    topic = cb.data.split(":", 2)[2] if cb.data.count(":") >= 2 else ""
    await state.set_state(SupportWrite.message)
    await state.update_data(topic=topic)
    await menu.show(bot, cb, "support")


@router.message(Command("mychats"))
async def cmd_mychats(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    from bot.handlers.chatadmin import show_list
    await show_list(bot, message)


@router.message(Command("shop"))
async def cmd_shop(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await menu.show(bot, message, "shop")


@router.message(Command("paysupport", "support"))
async def cmd_support(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.set_state(SupportWrite.message)
    await state.update_data(topic="оплата" if (message.text or "").startswith("/paysupport") else "")
    await menu.show(bot, message, "support")


@router.message(SupportWrite.message)
async def on_support_message(message: Message, bot: Bot, state: FSMContext) -> None:
    topic = (await state.get_data()).get("topic", "")
    await state.clear()
    user = message.from_user
    who = esc(full_name(user.first_name, user.last_name))
    if user.username:
        who += f" @{esc(user.username)}"
    header = (f"🆘 <b>Обращение в поддержку</b>{' · ' + esc(topic) if topic else ''}\n"
              f"От: {who} (<code>{user.id}</code>)")
    await db.support_add(user.id, full_name(user.first_name, user.last_name), user.username or "", topic, "in",
                         describe_dm(message))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✍️ Ответить", callback_data=f"sup:{user.id}", style="primary"),
        InlineKeyboardButton(text="✅ Закрыть", callback_data=f"su:x:{user.id}")],
        [InlineKeyboardButton(text="💬 Вся переписка", callback_data=f"su:t:{user.id}")]])
    delivered = False
    for owner in config.OWNER_IDS:
        try:
            await bot.send_message(owner, header, parse_mode="HTML")
            await bot.copy_message(owner, message.chat.id, message.message_id, reply_markup=kb)
            delivered = True
        except Exception as exc:
            log.warning("Обращение не дошло до %s: %s", owner, exc)
    back = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="sc:start")]])
    await message.answer("✅ Отправил, ответ придёт сюда же." if delivered
                         else "Не получилось отправить, попробуй позже.", reply_markup=back)


@router.message()
async def on_other(message: Message, bot: Bot, state: FSMContext) -> None:
    """Любое другое сообщение в личке: показываем меню."""
    await state.clear()
    await menu.show(bot, message, "start")


def describe_dm(message: Message) -> str:
    """Короткая запись сообщения для истории переписки поддержки."""
    text = message.text or message.caption or ""
    kind = ("[фото] " if message.photo else "[видео] " if message.video else "[голосовое] " if message.voice
            else "[файл] " if message.document else "[стикер] " if message.sticker else "")
    return (kind + text).strip() or "[сообщение]"
