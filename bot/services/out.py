"""Единая отправка сообщений бота в чаты. Здесь же чистка от длинных тире и кавычек-ёлочек,
чтобы ни одно сообщение бота (кроме рекламы, её текст не трогаем) не выдавало нейросеть."""

import contextvars

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions, Message, ReplyParameters

from bot.textutil import humanize

# внутри этого флага отправка идёт как есть: чужие рекламные посты и рассылки не трогаем
RAW = contextvars.ContextVar("raw_send", default=False)
_TEXT_FIELDS = ("text", "caption", "title", "description", "error_message")


async def sanitize_requests(make_request, bot, method):
    """Фильтр на ВСЕ запросы бота к Telegram: убирает длинные тире и кавычки-ёлочки
    из текстов, подписей, всплывашек, счетов и надписей на кнопках."""
    if RAW.get():
        return await make_request(bot, method)
    updates = {}
    for field in _TEXT_FIELDS:
        value = getattr(method, field, None)
        if isinstance(value, str):
            clean = humanize(value)
            if clean != value:
                updates[field] = clean
    markup = getattr(method, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None)
    if rows:
        new_rows = [[b.model_copy(update={"text": humanize(b.text)}) if humanize(b.text) != b.text else b for b in row]
                    for row in rows]
        if new_rows != rows:
            updates["reply_markup"] = InlineKeyboardMarkup(inline_keyboard=new_rows)
    if updates:
        method = method.model_copy(update=updates)
    return await make_request(bot, method)

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
