"""Команды владельца прямо в чате, где есть бот (другие люди их не видят и не могут нажать).

  /sub           показать подписку чата и кнопки: +7, +30, +90 дней, навсегда, бесплатный
  /sub 30        сразу предложить выдать 30 дней (любое число от 1 до 3650)
  /sub навсегда  без срока
  /sub бесплатно перевести на бесплатный тариф
Каждое действие с подтверждением: сначала кнопка «Да, выдать», только потом меняется подписка.
То же самое есть в админке: /admin → Чаты → чат → Доступ и аренда."""

import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import config, db
from bot.middlewares import GROUPS
from bot.services import approval
from bot.textutil import esc

log = logging.getLogger(__name__)
router = Router(name="owner_chat")

SUB_RE = re.compile(r"^\s*(/sub|подписка)(@\w+)?(?:\s+(\S+))?\s*$", re.I)
FOREVER = {"навсегда", "forever", "inf", "♾", "бессрочно"}
FREE = {"бесплатно", "бесплатный", "free", "фри"}


def _is_owner(user) -> bool:
    return bool(user) and user.id in config.OWNER_IDS


def _owner_sub(message: Message) -> dict | bool:
    if not _is_owner(message.from_user):
        return False
    m = SUB_RE.match(message.text or "")
    return {"arg": (m.group(3) or "").lower()} if m else False


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row]
                                                 for row in rows])


def _status(chat) -> str:
    if not chat["approved"]:
        return "⏳ ждёт одобрения"
    if chat["free"]:
        return "🆓 бесплатный (без ИИ)"
    if chat["rent_until"]:
        kind = "🎁 пробный" if chat["trial"] else "📅 подписка"
        return f"{kind} до {approval.until_text(chat['rent_until'])}"
    return "♾ без срока"


def _what(action: str) -> str:
    if action == "inf":
        return "♾ Сделать без срока"
    if action == "free":
        return "🆓 Перевести на бесплатный (нейросеть выключится)"
    return f"📅 Выдать {action} дн."


async def _confirm_text(chat, action: str) -> str:
    after = ""
    if action.isdigit():
        import time
        start = max(time.time(), chat["rent_until"] or 0) if not chat["free"] else time.time()
        after = f"\nБудет до <b>{approval.until_text(start + int(action) * 86400)}</b>"
    return (f"🔐 <b>Подписка чата {esc(chat['title'] or '')}</b>\n"
            f"Сейчас: {_status(chat)}\n\n{_what(action)}?{after}")


@router.message(F.chat.type.in_(GROUPS), F.text, _owner_sub)
async def cmd_sub(message: Message, arg: str) -> None:
    chat = await db.get_chat(message.chat.id)
    if chat is None:
        return
    if arg in FOREVER:
        action = "inf"
    elif arg in FREE:
        action = "free"
    elif arg.isdigit() and 1 <= int(arg) <= 3650:
        action = arg
    else:
        await message.reply(f"🔐 <b>Подписка чата</b>\nСейчас: {_status(chat)}\n\nЧто сделать?", parse_mode="HTML",
                            reply_markup=_kb([[("+7 дней", "os:ask:7"), ("+30 дней", "os:ask:30"),
                                               ("+90 дней", "os:ask:90")],
                                              [("♾ Навсегда", "os:ask:inf"), ("🆓 Бесплатный", "os:ask:free")],
                                              [("Отмена", "os:no")]]))
        return
    await message.reply(await _confirm_text(chat, action), parse_mode="HTML",
                        reply_markup=_kb([[("✅ Да", f"os:ok:{action}"), ("Отмена", "os:no")]]))


@router.callback_query(F.data.startswith("os:"))
async def cb_sub(cb: CallbackQuery, bot: Bot) -> None:
    if not _is_owner(cb.from_user):
        return await cb.answer("это только для владельца бота", show_alert=True)
    parts = cb.data.split(":")
    chat = await db.get_chat(cb.message.chat.id)
    if chat is None or parts[1] == "no":
        await cb.answer("отменил")
        try:
            await cb.message.delete()
        except Exception:
            pass
        return
    action = parts[2]
    if parts[1] == "ask":
        await cb.answer()
        await cb.message.edit_text(await _confirm_text(chat, action), parse_mode="HTML",
                                   reply_markup=_kb([[("✅ Да", f"os:ok:{action}"), ("Отмена", "os:no")]]))
        return
    cid = chat["chat_id"]
    if action == "inf":
        await approval.approve(bot, cid, announce=not chat["approved"])
        text = "♾ Готово: бот в этом чате работает без срока."
    elif action == "free":
        await db.update_chat(cid, approved=1, pending_since=0, rent_until=0, trial=0, free=1)
        text = "🆓 Готово: чат на бесплатном тарифе, игры и итоги работают, нейросеть выключена."
    else:
        await approval.approve(bot, cid, rent_days=int(action), announce=not chat["approved"])
        chat = await db.get_chat(cid)
        text = f"✅ Готово: подписка на {action} дн., бот работает до {approval.until_text(chat['rent_until'])}."
    log.info("Владелец %s в чате %s: подписка %s", cb.from_user.id, cid, action)
    await cb.answer("готово")
    await cb.message.edit_text(text)

