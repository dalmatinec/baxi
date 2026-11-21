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
    return await _with_flood_retry(make_request, bot, method)


async def _with_flood_retry(make_request, bot, method):
    """Telegram просит подождать (слишком много сообщений): ждём и пробуем ещё раз, а не теряем сообщение.
    Долгие паузы не ждём, чтобы бот не завис."""
    import asyncio

    from aiogram.exceptions import TelegramRetryAfter
    try:
        return await make_request(bot, method)
    except TelegramRetryAfter as exc:
        if exc.retry_after > 30:
            raise
        await asyncio.sleep(exc.retry_after + 0.5)
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


# чат → (кого тегать, имя): владелец включает в карточке чата, «🔔 Тегать»
TAGS: dict[int, tuple[int, str]] = {}


async def load_tags() -> None:
    from bot import db
    TAGS.clear()
    TAGS.update(await db.tag_map())


def with_tag(chat_id: int, html: str, reply_to: Message | None = None) -> str:
    """Дописывает упоминание человека в конец сообщения бота, если в этом чате так настроено.
    Если бот и так отвечает этому человеку, не дублируем."""
    tag = TAGS.get(chat_id)
    if not tag:
        return html
    uid, name = tag
    if reply_to is not None and reply_to.from_user and reply_to.from_user.id == uid:
        return html
    from bot.textutil import esc
    return f'{html} <a href="tg://user?id={uid}">{esc(name or "👤")}</a>'


async def say(bot: Bot, chat_id: int, html: str, *, reply_to: Message | None = None,
              thread: int | None = None, markup: InlineKeyboardMarkup | None = None) -> Message:
    from bot.services import emoji
    html = with_tag(chat_id, humanize(html), reply_to)
    pretty = emoji.decorate(html)
    kwargs = dict(parse_mode="HTML", link_preview_options=NO_PREVIEW, reply_parameters=reply_params(reply_to),
                  message_thread_id=thread if reply_to is None else None, reply_markup=markup)
    try:
        return await bot.send_message(chat_id, pretty, **kwargs)
    except Exception:
        if pretty == html:
            raise
        return await bot.send_message(chat_id, html, **kwargs)  # премиум-эмодзи не прошли: шлём обычные


async def say_photo(bot: Bot, chat_id: int, photo: str, html: str = "", *, reply_to: Message | None = None,
                    thread: int | None = None, markup: InlineKeyboardMarkup | None = None) -> Message:
    """Картинка с подписью (HTML, до 1024 символов), с теми же премиум-эмодзи, что и say."""
    from bot.services import emoji
    html = humanize(html) if html else ""
    pretty = emoji.decorate(html) if html else ""
    kwargs = dict(parse_mode="HTML", reply_parameters=reply_params(reply_to),
                  message_thread_id=thread if reply_to is None else None, reply_markup=markup)
    try:
        return await bot.send_photo(chat_id, photo, caption=pretty or None, **kwargs)
    except Exception:
        if pretty == html:
            raise
        return await bot.send_photo(chat_id, photo, caption=html or None, **kwargs)
