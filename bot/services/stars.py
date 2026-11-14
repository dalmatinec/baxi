"""Магазин за Telegram Stars.

В чате (команда «магазин» ответом на сообщение человека или «прожарь его по полной»):
  roast_full  прожарка по полной. Боту не нужны права админа.
Личное (в личке бота): vip (30 дней), shield (7 дней), донаты.
Звёзды выводятся владельцем через Fragment, возврат делается из админки."""

import logging
import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

from bot import ai, db, prompts
from bot.services import fun, talk
from bot.services.out import say
from bot.textutil import VIP_LOOK, esc, mention

log = logging.getLogger(__name__)

# ключ, название, цена в звёздах, порядок
DEFAULT_ITEMS = [
    ("roast_full", "🔥 Прожарка по полной", 30, 4),
    ("vip", "👑 VIP на 30 дней", 150, 5),
    ("shield", "🛡 Щит на 7 дней", 25, 6),
    ("don20", "💛 Поддержать: 20", 20, 7),
    ("don50", "💛 Поддержать: 50", 50, 8),
    ("don100", "💛 Поддержать: 100", 100, 9),
    ("don500", "💎 Поддержать: 500", 500, 10),
]
CHAT_ITEMS = ("roast_full",)
TARGET_ITEMS = ("roast_full",)   # нужен ответ на сообщение
PERSONAL_ITEMS = ("vip", "shield")
VIP_DAYS, SHIELD_DAYS = 30, 7

DESCRIPTIONS = {
    "roast_full": "Жёсткая смешная прожарка выбранного человека прямо в чате.",
    "vip": "Свой премиум-эмодзи и жирный ник у имени везде, где бот тебя упоминает, особое приветствие "
           "при входе, итоги без лимита. 30 дней.",
    "shield": "7 дней тебя нельзя прожарить ни в одном чате.",
}


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


async def chat_shop(bot: Bot, chat, message: Message) -> None:
    """Команда «магазин» в чате. Если это ответ на сообщение, товары для этого человека тоже доступны."""
    items = await items_map()
    rt = message.reply_to_message
    target = rt.from_user if rt and rt.from_user and not rt.from_user.is_bot else None
    lines = ["🛒 <b>Магазин чата</b>"]
    buttons = []
    for key in CHAT_ITEMS:
        item = items.get(key)
        if not item:
            continue
        lines.append(f"<b>{esc(item['title'])}</b> · {item['stars']} ⭐\n<i>{esc(item_text(key))}</i>")
        if key in TARGET_ITEMS and not target:
            continue
        link = await bot.create_invoice_link(
            title=item["title"][:32], description=item_text(key)[:255], currency="XTR",
            payload=payload(key, chat["chat_id"], target.id if target else 0),
            prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])])
        who = f" → {target.first_name}" if target else ""
        buttons.append([InlineKeyboardButton(text=f"{item['title']}{who} · {item['stars']} ⭐", url=link,
                                             style="danger")])
    if not target:
        lines.append("💡 <i>Чтобы заказать прожарку, ответь словом магазин на сообщение нужного человека "
                     "или напиши мне: прожарь его по полной.</i>")
    me = await bot.me()
    buttons.append([InlineKeyboardButton(text="👑 VIP и 🛡 щит: в личке", url=f"https://t.me/{me.username}?start=shop")])
    await say(bot, chat["chat_id"], "\n\n".join(lines), reply_to=message,
              markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def check(bot: Bot, raw_payload: str, buyer_id: int) -> str | None:
    """Проверка перед оплатой. Строка: почему нельзя купить. None: можно."""
    p = parse_payload(raw_payload)
    if p["item"] == "roast_full" and await shielded(p.get("target")):
        return "У этого человека щит 🛡, не пробить"
    if p["item"] == "roast_full" and p.get("target"):
        chat = await db.get_chat(p["chat_id"])
        why = await fun.protected(bot, chat, p["target"]) if chat else ""
        if why:
            return why[:100]
    return None


async def apply(bot: Bot, raw_payload: str, buyer_id: int, buyer_name: str) -> str:
    """Выполняет покупку. Возвращает, что ответить покупателю в личке."""
    p = parse_payload(raw_payload)
    item = p["item"]
    now = time.time()
    perks = await db.get_perks(buyer_id)
    if item == "vip":
        start = max(now, perks["vip_until"] if perks else 0)
        await db.set_perks(buyer_id, vip_until=start + VIP_DAYS * 86400)
        await refresh_looks()
        return (f"👑 Ты VIP на {VIP_DAYS} дней!\n\nНастрой свой вид: премиум-эмодзи и ник, которые будут "
                "у твоего имени везде, где бот тебя упоминает. Меню → Магазин → Мой VIP.")
    if item == "shield":
        start = max(now, perks["shield_until"] if perks else 0)
        await db.set_perks(buyer_id, shield_until=start + SHIELD_DAYS * 86400)
        return f"🛡 Щит включён на {SHIELD_DAYS} дней. Тебя не прожарить."
    if item.startswith("don"):
        return f"💛 Спасибо за поддержку, {esc(buyer_name)}! Ты в топе донатеров."
    chat_id, target = p["chat_id"], p["target"]
    if item == "roast_full":
        await do_full_roast(bot, chat_id, target, buyer_name, buyer_id)
        return "🔥 Жарю в чате!"
    return "Готово."


async def expire_titles(bot: Bot) -> None:
    """Снимает подписи, купленные, когда в магазине ещё была должность."""
    for row in await db.expired_titles(time.time()):
        try:
            await bot.promote_chat_member(row["chat_id"], row["user_id"], can_invite_users=False)
        except Exception as exc:
            log.info("Не снял должность %s в %s: %s", row["user_id"], row["chat_id"], exc)
        await db.delete_chat_title(row["chat_id"], row["user_id"])


async def offer_full_roast(bot: Bot, chat, message: Message, author_row) -> None:
    """В чате попросили «прожарь по полной»: проверяем щит и даём кнопку оплаты."""
    items = await items_map()
    item = items.get("roast_full")
    if not item or not chat["shop"]:  # магазин в чате выключен: обычная бесплатная прожарка
        return await fun.roast(bot, chat, message, author_row)
    target = await fun.roast_target(bot, chat["chat_id"], message)
    if target is None:
        await say(bot, chat["chat_id"], "кого жарить по полной? ответь на его сообщение или назови имя",
                  reply_to=message)
        return
    if await shielded(target["user_id"]):
        await say(bot, chat["chat_id"], f"у {mention(target['user_id'], target['name'])} щит 🛡, не пробить",
                  reply_to=message)
        return
    link = await bot.create_invoice_link(
        title="🔥 Прожарка по полной", description=f"Жёсткая прожарка: {target['name']}"[:255], currency="XTR",
        payload=payload("roast_full", chat["chat_id"], target["user_id"]),
        prices=[LabeledPrice(label="Прожарка по полной", amount=item["stars"])])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"🔥 Прожарить за {item['stars']} ⭐", url=link, style="danger")]])
    await say(bot, chat["chat_id"], f"прожарка по полной для {mention(target['user_id'], target['name'])} "
                                    f"стоит {item['stars']} ⭐. жми, и я начну", reply_to=message, markup=kb)


async def do_full_roast(bot: Bot, chat_id: int, target_id: int, buyer_name: str, buyer_id: int = 0) -> None:
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
                            f"<i>заказал {mention(buyer_id, buyer_name) if buyer_id else esc(buyer_name)}</i>"
                            f"\n\n{esc(text)}")
