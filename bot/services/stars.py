"""Мелкие покупки за Telegram Stars: донаты, титул в топах, щит от прожарки, прожарка по полной.
Деньги со звёзд идут владельцу бота (вывод через Fragment), возврат делается из супер-админки."""

import logging
import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

from bot import ai, db, prompts
from bot.services import fun, talk
from bot.services.out import say
from bot.textutil import esc, mention

log = logging.getLogger(__name__)

DEFAULT_ITEMS = [
    ("don20", "⭐ Поддержать бота: 20", 20, 0),
    ("don50", "⭐ Поддержать бота: 50", 50, 1),
    ("don100", "🌟 Поддержать бота: 100", 100, 2),
    ("don500", "💎 Поддержать бота: 500", 500, 3),
    ("title", "👑 Свой титул в топах на 30 дней", 50, 4),
    ("shield", "🛡 Щит от прожарки на 7 дней", 25, 5),
    ("roast_full", "🔥 Прожарка по полной", 30, 6),
]
TITLE_DAYS = 30
SHIELD_DAYS = 7


def item_text(key: str) -> str:
    return {
        "title": f"Твой титул будет рядом с именем во всех топах {TITLE_DAYS} дней. Придумаешь сам после оплаты.",
        "shield": f"{SHIELD_DAYS} дней тебя нельзя прожарить ни в одном чате.",
        "roast_full": "Жёсткая прожарка выбранного человека прямо в чате. Покупается в чате: ответь на "
                      "сообщение человека словами «<имя бота>, прожарь по полной».",
    }.get(key, "Поддержка бота. Попадёшь в топ донатеров и в нашу благодарность 💛")


async def invoice(bot: Bot, chat_id: int, key: str, payload: str | None = None) -> None:
    item = await db.shop_item(key)
    if not item:
        return
    await bot.send_invoice(chat_id, title=item["title"][:32], description=item_text(key)[:255],
                           payload=payload or key, currency="XTR",
                           prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])])


async def shielded(user_id: int) -> float:
    """До какого времени у человека щит (0, если нет)."""
    perks = await db.get_perks(user_id)
    return perks["shield_until"] if perks and perks["shield_until"] > time.time() else 0


async def decorate(rows, name_key: str = "name") -> dict[int, str]:
    """Имя + активный титул для топов: {user_id: 'Аня · Королева чата'}."""
    titles = await db.active_titles([r["user_id"] for r in rows])
    return {r["user_id"]: r[name_key] + (f" · {titles[r['user_id']]}" if r["user_id"] in titles else "")
            for r in rows}


async def offer_full_roast(bot: Bot, chat, message: Message, author_row) -> None:
    """В чате попросили «прожарь по полной»: проверяем щит и даём кнопку оплаты."""
    item = await db.shop_item("roast_full")
    if not item or not item["enabled"]:
        return await fun.roast(bot, chat, message, author_row)
    target = await fun.roast_target(bot, chat["chat_id"], message)
    if target is None:
        await say(bot, chat["chat_id"], "кого жарить по полной? ответь на его сообщение или назови имя",
                  reply_to=message)
        return
    if await shielded(target["user_id"]):
        await say(bot, chat["chat_id"], f"у {esc(target['name'])} щит от прожарки 🛡, не пробить", reply_to=message)
        return
    link = await bot.create_invoice_link(
        title="🔥 Прожарка по полной", description=f"Жёсткая прожарка: {target['name']}"[:255],
        payload=f"roast:{chat['chat_id']}:{target['user_id']}", currency="XTR",
        prices=[LabeledPrice(label="Прожарка по полной", amount=item["stars"])])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"🔥 Прожарить за {item['stars']} ⭐", url=link, style="danger")]])
    await say(bot, chat["chat_id"], f"прожарка по полной для {mention(target['user_id'], target['name'])} "
                                    f"стоит {item['stars']} ⭐. жми, и я начну", reply_to=message, markup=kb)


async def do_full_roast(bot: Bot, chat_id: int, target_id: int, buyer_name: str) -> None:
    chat = await db.get_chat(chat_id)
    target = await db.get_user(chat_id, target_id)
    if not chat or not target:
        return
    messages = await db.user_messages(chat_id, target_id, 40)
    system, _ = await talk.context(chat)
    task = prompts.roast_task(target["name"], target["notes"], messages, "") + (
        " Это прожарка ПО ПОЛНОЙ: 5-7 предложений, максимально жёстко и смешно, мат можно, "
        "но правила про национальность, религию, внешность и здоровье остаются.")
    answer = await ai.chat([{"role": "system", "content": system}, {"role": "user", "content": task}],
                           max_tokens=600, temperature=1.15)
    text = prompts.clean_reply(answer or "", chat["bot_name"], limit=1500) or \
        f"{target['name']}, я хотел тебя прожарить, но ты и так уже угли"
    await say(bot, chat_id, f"🔥🔥🔥 <b>Прожарка по полной:</b> {mention(target_id, target['name'])}\n"
                            f"<i>заказал {esc(buyer_name)}</i>\n\n{esc(text)}")
