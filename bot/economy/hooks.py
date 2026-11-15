"""Связка экономики с ботом: что происходит при сообщении в чате, после оплаты звёздами и по расписанию.
Вызывается из middlewares.GroupTracker, services/stars.apply и services/daily.tick."""

import logging
import random
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import config, db
from bot.economy import catalog, service, store
from bot.services.out import say
from bot.textutil import esc, mention

log = logging.getLogger(__name__)

LEVEL_UP = [
    "🎉 {who} теперь <b>{level} уровень</b> · {title}! Держи {coins} 🪙",
    "🆙 {who} дорос до <b>{level} уровня</b> · {title}. Награда {coins} 🪙",
    "⭐ {who}, <b>{level} уровень</b>! Новое звание: {title}. +{coins} 🪙",
]
HUNGRY = [
    "🍽 {pet} у {who} проголодался! Покормите: {food}",
    "😿 {who}, твой {pet} голодный и грустит. Ему бы {food}",
    "🥺 {pet} смотрит на {who} голодными глазами. Нужно {food}",
]


def enabled(chat) -> bool:
    """Экономика включена тумблером «Монеты и питомцы» (колонка shop в настройках чата)."""
    return bool(chat and chat["shop"])


async def on_group_message(bot: Bot, chat, message: Message, name: str) -> None:
    """Каждое сообщение в чате: опыт и монеты (не чаще 2 раз в минуту), поздравление с уровнем."""
    if not enabled(chat) or message.content_type != "text":
        return
    up = await service.on_message(chat["chat_id"], message.from_user.id, name, message.text or "")
    if not up or up[1] < catalog.ANNOUNCE_FROM:
        return
    level = up[1]
    coins = catalog.LEVEL_REWARD * level
    await store.add_coins(chat["chat_id"], message.from_user.id, coins)
    text = random.choice(LEVEL_UP).format(who=mention(message.from_user.id, name), level=level,
                                          title=catalog.title_for(level), coins=coins)
    try:
        await say(bot, chat["chat_id"], text)
    except Exception as exc:
        log.info("Поздравление с уровнем не ушло: %s", exc)


# ---------- после оплаты звёздами ----------

async def paid_coins(bot: Bot, chat_id: int, user_id: int, name: str, coins: int) -> str:
    balance = await store.add_coins(chat_id, user_id, coins, name)
    chat = await db.get_chat(chat_id)
    try:
        await say(bot, chat_id, f"💰 {mention(user_id, name)} пополнил кошелёк на <b>{coins} 🪙</b>")
    except Exception:
        pass
    return f"💰 Готово! +{coins} 🪙 в чате {esc(chat['title'] if chat else '')}. Баланс: <b>{balance} 🪙</b>"


async def paid_pet(bot: Bot, chat_id: int, user_id: int, name: str, species: str) -> str:
    info = catalog.PETS[species]
    await service.give_pet(chat_id, user_id, name, species)
    try:
        await say(bot, chat_id, f"{info['emoji']} У {mention(user_id, name)} теперь редкий питомец: "
                                f"<b>{info['name']}</b>! Сила {info['power']} 💪")
    except Exception:
        pass
    return f"{info['emoji']} {info['name']} теперь твой! Посмотреть: напиши в чате питомец."


# ---------- по расписанию ----------

def feed_kb(owner_id: int, species: str) -> InlineKeyboardMarkup:
    """Кнопки выбора корма. В callback хозяин питомца: покормить можно и чужого, платит нажавший."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{f['emoji']} {f['name']} · {f['price']} 🪙", callback_data=f"eco:f:{owner_id}:{f['key']}",
                             style="success" if f["key"] == "food" else None)
        for f in catalog.foods(species)]])


async def tick(bot: Bot) -> None:
    """Раз в минуту: возврат ставок из брошенных костей, днём напоминание о голодных питомцах."""
    for d in await service.refund_expired():
        if d.accepted:
            try:
                await say(bot, d.chat_id, f"🎲 {mention(d.a, d.a_name)} и {mention(d.b, d.b_name)} не докинули кости, "
                                          f"ставки по {d.bet} 🪙 вернул")
            except Exception:
                pass
    if not 10 <= datetime.now(config.TZ).hour < 22:
        return
    for chat in await db.list_chats():
        if not enabled(chat):
            continue
        for pet in (await service.hungry_pets(chat["chat_id"]))[:1]:  # не больше одного напоминания за раз
            await store.update_pet(chat["chat_id"], pet["user_id"], warned=1)
            food = catalog.PETS[pet["species"]]["food"]
            emoji = catalog.PETS[pet["species"]]["emoji"]
            text = random.choice(HUNGRY).format(pet=f"{emoji} <b>{esc(pet['name'])}</b>",
                                                who=mention(pet["user_id"], pet["owner"]), food=f"{food[0]} {food[1]}")
            try:
                await say(bot, chat["chat_id"], text, markup=feed_kb(pet["user_id"], pet["species"]))
            except Exception as exc:
                log.info("Напоминание о голодном питомце не ушло: %s", exc)
