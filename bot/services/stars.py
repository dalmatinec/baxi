"""Магазин за Telegram Stars. Звёзды только пополняют монеты, остальное покупается за монеты.

В чате (команда «магазин», bot/handlers/economy.py):
  c1500 … c25000   пачки монет для этого чата (то же самое можно оплатить USDT, см. handlers/economy.py)
Магазин в личке пока скрыт. VIP, щит и прожарку за звёзды больше не продаём: уже купленные доживают срок.
Звёзды выводятся владельцем через Fragment, возврат делается из админки."""

import logging
import time

from aiogram import Bot
from aiogram.types import Message

from bot import db
from bot.economy import catalog
from bot.textutil import VIP_LOOK, esc

log = logging.getLogger(__name__)

# ключ, название, цена в звёздах, порядок (цены владелец меняет в админке)
DEFAULT_ITEMS = [(key, f"🪙 {coins} монет", price, n) for n, (key, (coins, price, _)) in enumerate(catalog.COIN_PACKS.items())]
DEFAULT_ITEMS += [
    ("don20", "💛 Поддержать: 20", 20, 7),
    ("don50", "💛 Поддержать: 50", 50, 8),
    ("don100", "💛 Поддержать: 100", 100, 9),
    ("don500", "💎 Поддержать: 500", 500, 10),
]
CHAT_ITEMS = tuple(catalog.COIN_PACKS)

DESCRIPTIONS = {key: f"{pack[0]} монет на твой кошелёк в этом чате" for key, pack in catalog.COIN_PACKS.items()}


def item_text(key: str) -> str:
    return DESCRIPTIONS.get(key, "Поддержка бота. Попадёшь в топ донатеров 💛")


async def items_map() -> dict[str, object]:
    await db.seed_shop(DEFAULT_ITEMS)
    return {i["key"]: i for i in await db.shop_items()}


# ---------- статусы ----------

async def shielded(user_id: int) -> float:
    """До какого времени у человека щит (0, если нет)."""
    perks = await db.get_perks(user_id)
    return perks["shield_until"] if perks and perks["shield_until"] > time.time() else 0


async def is_vip(user_id: int) -> bool:
    return user_id in await db.vip_ids([user_id])


async def has_look(user_id: int) -> bool:
    """Можно ли настраивать свой ник и эмодзи: ник куплен за монеты навсегда или ещё действует старый VIP."""
    perks = await db.get_perks(user_id)
    return bool(perks and (perks["look_forever"] or perks["vip_until"] > time.time()))


async def decorate(rows, name_key: str = "name") -> dict[int, str]:
    """Имя для топов с титулом, если есть. Вид VIP (эмодзи, ник) добавляет сам mention()."""
    titles = await db.active_titles([r["user_id"] for r in rows])
    return {r["user_id"]: r[name_key] + (f" · {titles[r['user_id']]}" if r["user_id"] in titles else "")
            for r in rows}


async def refresh_looks() -> None:
    """Перечитать вид всех действующих VIP: после покупки, смены эмодзи или ника и раз в минуту."""
    looks = {r["user_id"]: (r["emoji_id"], r["emoji_alt"], r["nick"]) for r in await db.vip_looks()}
    VIP_LOOK.clear()
    VIP_LOOK.update(looks)


def custom_emoji(message: Message) -> tuple[str, str] | None:
    """Первый премиум-эмодзи в сообщении: (id, сам символ). Смещения в Telegram считаются в UTF-16."""
    text = message.text or message.caption or ""
    raw = text.encode("utf-16-le")
    for ent in message.entities or message.caption_entities or []:
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            alt = raw[ent.offset * 2:(ent.offset + ent.length) * 2].decode("utf-16-le", errors="ignore")
            return ent.custom_emoji_id, alt or "👑"
    return None


def clean_nick(text: str) -> str | None:
    nick = " ".join((text or "").split())
    if not nick or len(nick) > 24 or "http" in nick.lower() or "@" in nick or "t.me" in nick.lower():
        return None
    return nick


# ---------- магазин в чате ----------

def payload(item: str, chat_id: int, target: int = 0, msg: int = 0) -> str:
    return f"c:{item}:{chat_id}:{target}:{msg}"


def parse_payload(p: str) -> dict:
    parts = p.split(":")
    if parts[0] == "c" and len(parts) == 5:
        return {"item": parts[1], "chat_id": int(parts[2]), "target": int(parts[3]), "msg": int(parts[4])}
    return {"item": parts[0]}


async def check(bot: Bot, raw_payload: str, buyer_id: int) -> str | None:
    """Проверка перед оплатой. Строка: почему нельзя купить. None: можно."""
    p = parse_payload(raw_payload)
    if p["item"] in catalog.COIN_PACKS and not p.get("chat_id"):
        return "Пополнять монеты нужно из чата: напиши там магазин"
    return None


async def apply(bot: Bot, raw_payload: str, buyer_id: int, buyer_name: str) -> str:
    """Выполняет покупку. Возвращает, что ответить покупателю в личке."""
    p = parse_payload(raw_payload)
    item = p["item"]
    if item.startswith("don"):
        return f"💛 Спасибо за поддержку, {esc(buyer_name)}! Ты в топе донатеров."
    from bot.economy import hooks
    if item in catalog.COIN_PACKS and p.get("chat_id"):
        return await hooks.paid_coins(bot, p["chat_id"], buyer_id, buyer_name, catalog.COIN_PACKS[item][0])
    return "Готово."


async def expire_titles(bot: Bot) -> None:
    """Снимает подписи, купленные, когда в магазине ещё была должность."""
    for row in await db.expired_titles(time.time()):
        try:
            await bot.promote_chat_member(row["chat_id"], row["user_id"], can_invite_users=False)
        except Exception as exc:
            log.info("Не снял должность %s в %s: %s", row["user_id"], row["chat_id"], exc)
        await db.delete_chat_title(row["chat_id"], row["user_id"])
