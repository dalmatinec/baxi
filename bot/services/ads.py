"""Реклама: пост с кнопками-ссылками уходит по чатам с заданным интервалом.
Планировщик раз в 30 секунд смотрит, кому пора отправить."""

import asyncio
import json
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import db

log = logging.getLogger(__name__)

CHECK_EVERY = 30  # секунд


def markup(buttons) -> InlineKeyboardMarkup | None:
    rows = json.loads(buttons) if isinstance(buttons, str) else buttons
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b[0], url=b[1], style=b[2] if len(b) > 2 and b[2] else None) for b in row]
        for row in rows])


def extract_post(message: Message) -> tuple[str, str, str] | str:
    """(тип медиа, file_id, html-текст) или строка с ошибкой."""
    if message.photo:
        kind, file_id = "photo", message.photo[-1].file_id
    elif message.video:
        kind, file_id = "video", message.video.file_id
    elif message.animation:
        kind, file_id = "gif", message.animation.file_id
    elif message.text:
        kind, file_id = "", ""
    else:
        return "Пришли текст, фото, видео или гифку (можно с подписью)."
    if kind and message.caption and len(message.caption) > 1024:
        return "Подпись к медиа длиннее 1024 символов, Telegram такое не отправит. Сократи."
    html = message.html_text if (message.text or message.caption) else ""
    return kind, file_id, html



async def send_ad(bot: Bot, ad, chat_id: int) -> int:
    """Отправляет пост в чат и возвращает id сообщения."""
    kb = markup(ad["buttons"])
    text = ad["text_html"] or None
    kind = ad["media_kind"]
    if kind == "photo":
        msg = await bot.send_photo(chat_id, ad["file_id"], caption=text, parse_mode="HTML", reply_markup=kb)
    elif kind == "video":
        msg = await bot.send_video(chat_id, ad["file_id"], caption=text, parse_mode="HTML", reply_markup=kb)
    elif kind == "gif":
        msg = await bot.send_animation(chat_id, ad["file_id"], caption=text, parse_mode="HTML", reply_markup=kb)
    else:
        msg = await bot.send_message(chat_id, text or "…", parse_mode="HTML", reply_markup=kb)
    return msg.message_id


async def post_to_chat(bot: Bot, ad, chat_id: int) -> bool:
    prev = await db.get_ad_send(ad["id"], chat_id)
    if ad["delete_prev"] and prev and prev["message_id"]:
        try:
            await bot.delete_message(chat_id, prev["message_id"])
        except Exception:
            pass  # старый пост уже удалили руками или прошло больше 48 часов
    try:
        message_id = await send_ad(bot, ad, chat_id)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 1)
        return False
    except TelegramForbiddenError:
        log.warning("Чат %s закрыт для бота, выключаю его", chat_id)
        await db.update_chat(chat_id, active=0)
        return False
    except Exception as exc:
        log.warning("Реклама %s не ушла в чат %s: %s", ad["id"], chat_id, exc)
        # запоминаем попытку, чтобы не долбить чат каждые 30 секунд
        await db.set_ad_send(ad["id"], chat_id, 0)
        return False
    await db.set_ad_send(ad["id"], chat_id, message_id)
    return True


async def tick(bot: Bot) -> int:
    from bot.services import license
    if license.sleeping():
        return 0
    sent = 0
    now = time.time()
    chats = [c for c in await db.list_chats() if c["ads"]]
    for ad in await db.list_ads(enabled_only=True):
        for chat in chats:
            prev = await db.get_ad_send(ad["id"], chat["chat_id"])
            if prev and now - prev["last_sent"] < ad["interval"] * 60:
                continue
            if await post_to_chat(bot, ad, chat["chat_id"]):
                sent += 1
            await asyncio.sleep(1)  # не спамим Telegram пачкой
    return sent


async def run_scheduler(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в планировщике рекламы")
        await asyncio.sleep(CHECK_EVERY)
