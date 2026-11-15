"""Связка экономики с ботом: что происходит при сообщении в чате, после оплаты и по расписанию.
Вызывается из middlewares.GroupTracker, после оплаты (звёзды: services/stars.apply, USDT: services/adorders)
и из services/daily.tick. Тексты сообщений владелец меняет в админке (services/texts.py)."""

import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import config
from bot.economy import catalog, service, store
from bot.services import texts
from bot.services.out import say
from bot.textutil import esc, mention

log = logging.getLogger(__name__)


def enabled(chat) -> bool:
    """Экономика в чате включена тумблером «Монеты и питомцы» (колонка shop в настройках чата)."""
    return bool(chat and chat["shop"])


async def on_group_message(bot: Bot, chat, message: Message, name: str) -> None:
    """Каждое сообщение в чате: опыт и монеты (не чаще 2 раз в минуту), поздравление с уровнем."""
    if not enabled(chat) or message.content_type != "text":
        return
    up = await service.on_message(message.from_user.id, name, message.text or "")
    if not up or up[1] < catalog.ANNOUNCE_FROM:
        return
    level = up[1]
    coins = catalog.LEVEL_REWARD * level
    await store.add_coins(message.from_user.id, coins)
    text = await texts.render("eco_level", кто=mention(message.from_user.id, name), уровень=level,
                              звание=catalog.title_for(level), монеты=coins)
    try:
        await say(bot, chat["chat_id"], text)
    except Exception as exc:
        log.info("Поздравление с уровнем не ушло: %s", exc)


# ---------- после оплаты ----------

async def paid_coins(bot: Bot, user_id: int, name: str, coins: int) -> str:
    """Монеты пришли (звёзды или USDT). Возвращает текст для лички покупателя."""
    balance = await store.add_coins(user_id, coins, name)
    return (await texts.render("eco_topup", кто=esc(name), сколько=coins)
            + f"\n\n💰 Баланс: <b>{balance} 🪙</b>")


# ---------- кнопки корма ----------

def feed_kb(owner_id: int, species: str, extra: list | None = None) -> InlineKeyboardMarkup:
    """Кнопки выбора корма. В callback хозяин питомца: покормить можно и чужого, платит нажавший."""
    rows = [[InlineKeyboardButton(text=f"{f['emoji']} {f['name']} · {f['price']} 🪙",
                                  callback_data=f"ef:{owner_id}:{f['key']}",
                                  style="success" if f["key"] == "food" else None)
             for f in catalog.foods(species)]]
    return InlineKeyboardMarkup(inline_keyboard=rows + (extra or []))


# ---------- по расписанию ----------

async def tick(bot: Bot) -> None:
    """Раз в минуту: возврат ставок из брошенных костей, днём хозяевам голодных питомцев пишем в личку."""
    for d in await service.refund_expired():
        if d.accepted:
            try:
                await say(bot, d.chat_id, f"🎲 {mention(d.a, d.a_name)} и {mention(d.b, d.b_name)} не докинули кости, "
                                          f"ставки по {d.bet} 🪙 вернул")
            except Exception:
                pass
    if not 10 <= datetime.now(config.TZ).hour < 22:
        return
    for pet in (await service.hungry_pets())[:20]:   # не больше 20 сообщений за минуту
        await store.update_pet(pet["user_id"], warned=1)
        food = catalog.PETS[pet["species"]]["food"]
        emoji = catalog.PETS[pet["species"]]["emoji"]
        text = await texts.render("eco_hungry", питомец=f"{emoji} <b>{esc(pet['name'])}</b>",
                                  хозяин=mention(pet["user_id"], pet["owner"]), корм=f"{food[0]} {food[1]}")
        try:
            await say(bot, pet["user_id"], text, markup=feed_kb(pet["user_id"], pet["species"]))
        except Exception as exc:
            log.info("Хозяину голодного питомца не написал (не запускал бота?): %s", exc)
