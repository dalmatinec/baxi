"""Ответы на обращения в поддержку: владелец жмёт «Ответить» и пишет ответ, бот пересылает его человеку."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

router = Router(name="admin-support")


class SupportReply(StatesGroup):
    message = State()


@router.callback_query(F.data.startswith("sup:"))
async def cb_reply(cb: CallbackQuery, state: FSMContext) -> None:
    user_id = int(cb.data.split(":")[1])
    await state.set_state(SupportReply.message)
    await state.update_data(user_id=user_id)
    await cb.message.answer(f"✍️ Напиши ответ для <code>{user_id}</code> (текст, фото, что угодно) или /cancel",
                            parse_mode="HTML")
    await cb.answer()


@router.message(SupportReply.message)
async def on_reply(message: Message, bot: Bot, state: FSMContext) -> None:
    user_id = (await state.get_data())["user_id"]
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🆘 Написать ещё", callback_data="act:support", style="primary"),
        InlineKeyboardButton(text="⬅️ В меню", callback_data="sc:start")]])
    try:
        await bot.send_message(user_id, "💬 <b>Ответ поддержки:</b>", parse_mode="HTML")
        await bot.copy_message(user_id, message.chat.id, message.message_id, reply_markup=kb)
        await message.answer("✅ Ответ доставлен")
    except Exception as exc:
        await message.answer(f"Не доставлено: {str(exc)[:200]}")
