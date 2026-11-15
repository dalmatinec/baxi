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
    """Каждое сообщение в чате: ранг в чате, общий уровень и монеты (не чаще 2 раз в минуту).
    Новый ранг в чате поздравляем в чате, новый общий уровень в личке (там же новые плюшки)."""
    if not enabled(chat) or message.content_type != "text":
        return
    uid = message.from_user.id
    up = await service.on_message(chat["chat_id"], uid, name, message.text or "")
    if up["chat"] and up["chat"][1] >= catalog.ANNOUNCE_FROM:
        level = up["chat"][1]
        coins = catalog.CHAT_RANK_REWARD * level
        await store.add_coins(uid, coins)
        try:
            await say(bot, chat["chat_id"], await texts.render(
                "eco_level", кто=mention(uid, name), уровень=level, звание=catalog.title_for(level), монеты=coins))
        except Exception as exc:
            log.info("Поздравление с рангом не ушло: %s", exc)
    if up["global"] and up["global"][1] >= catalog.ANNOUNCE_FROM:
        level = up["global"][1]
        coins = catalog.LEVEL_REWARD * level
        await store.add_coins(uid, coins)
        perks = catalog.perks_text(catalog.perks_for(level))
        if catalog.perks_for(level) != catalog.perks_for(up["global"][0]):
            perks = "🆕 " + perks
        try:
            await say(bot, uid, await texts.render("eco_level_global", кто=esc(name), уровень=level,
                                                   звание=catalog.title_for(level), монеты=coins, плюшки=perks))
        except Exception:
            pass   # человек не запускал бота в личке: монеты всё равно начислены


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

MEDALS = ["🥇", "🥈", "🥉"]


async def weekly(bot: Bot) -> None:
    """Воскресенье вечером: в каждом чате топ-3 по сообщениям за неделю получают монеты."""
    from datetime import timedelta

    from bot import db
    now = datetime.now(config.TZ)
    if now.weekday() != catalog.WEEKLY_DAY or now.hour != catalog.WEEKLY_HOUR:
        return
    week = now.strftime("%G-%V")
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    for chat in await db.list_chats():
        if not enabled(chat) or await db.kv_get(f"weekly_{chat['chat_id']}") == week:
            continue
        await db.kv_set(f"weekly_{chat['chat_id']}", week)
        top = [r for r in await db.top_talkers(chat["chat_id"], days, 3) if r["msgs"] >= catalog.WEEKLY_MIN_MSGS]
        if not top:
            continue
        lines = []
        for i, r in enumerate(top):
            prize = catalog.WEEKLY_PRIZES[i]
            await store.add_coins(r["user_id"], prize, r["name"])
            lines.append(f"{MEDALS[i]} {mention(r['user_id'], r['name'])} · {r['msgs']} сообщ. · +{prize} 🪙")
        try:
            await say(bot, chat["chat_id"], await texts.render("eco_weekly", список="\n".join(lines)))
        except Exception as exc:
            log.info("Итоги недели в %s не ушли: %s", chat["chat_id"], exc)


async def tick(bot: Bot) -> None:
    """Раз в минуту: возврат ставок из брошенных костей, призы недели, днём хозяевам голодных питомцев пишем в личку."""
    await weekly(bot)
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
