"""Единая отправка сообщений бота в чаты. Здесь же чистка от длинных тире и кавычек-ёлочек,
чтобы ни одно сообщение бота (кроме рекламы, её текст не трогаем) не выдавало нейросеть."""

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions, Message, ReplyParameters

from bot.textutil import humanize

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def reply_params(message: Message | None) -> ReplyParameters | None:
    if message is None:
        return None
    return ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True)


def thread_of(message: Message | None) -> int | None:
    """Ветка форума, если в группе включены темы: пишем в ту же ветку."""
    if message is not None and message.is_topic_message:
        return message.message_thread_id
    return None


async def say(bot: Bot, chat_id: int, html: str, *, reply_to: Message | None = None,
              thread: int | None = None, markup: InlineKeyboardMarkup | None = None) -> Message:
    return await bot.send_message(
        chat_id, humanize(html), parse_mode="HTML", link_preview_options=NO_PREVIEW,
        reply_parameters=reply_params(reply_to),
        message_thread_id=thread if reply_to is None else None,
        reply_markup=markup)
