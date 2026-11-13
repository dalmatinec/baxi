"""Личка с ботом для обычных людей (не владельцев)."""

from aiogram import F, Router
from aiogram.types import Message

router = Router(name="private")


@router.message(F.chat.type == "private")
async def on_stranger(message: Message) -> None:
    await message.answer("привет 🙂 я живу в чатах, тут мне скучно. заходи в чат, там поболтаем")
