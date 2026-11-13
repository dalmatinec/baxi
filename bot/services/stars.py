"""Магазин за Telegram Stars.

В чате (команда «магазин», для мута/пары/закрепа/прожарки ответом на сообщение человека):
  pos         должность: настоящая подпись у имени в чате на 30 дней
  mute        мут человека на 15 минут
  pin         закреп сообщения на 2 часа
  pair        пара дня с выбранным человеком
  roast_full  прожарка по полной
Личное (в личке бота): vip (30 дней), shield (7 дней), донаты.
Звёзды выводятся владельцем через Fragment, возврат делается из админки."""

import logging
import time

from aiogram import Bot
from aiogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

from bot import ai, db, prompts
from bot.services import fun, talk
from bot.services.out import say
from bot.textutil import esc, mention

log = logging.getLogger(__name__)

# ключ, название, цена в звёздах, порядок
DEFAULT_ITEMS = [
    ("pos", "🏷 Должность у имени на 30 дней", 100, 0),
    ("mute", "🔇 Мут на 15 минут", 25, 1),
    ("pin", "📌 Закреп сообщения на 2 часа", 30, 2),
    ("pair", "💘 Пара дня с кем хочешь", 20, 3),
    ("roast_full", "🔥 Прожарка по полной", 30, 4),
    ("vip", "👑 VIP на 30 дней", 150, 5),
    ("shield", "🛡 Щит на 7 дней", 25, 6),
    ("don20", "💛 Поддержать: 20", 20, 7),
    ("don50", "💛 Поддержать: 50", 50, 8),
    ("don100", "💛 Поддержать: 100", 100, 9),
    ("don500", "💎 Поддержать: 500", 500, 10),
]
CHAT_ITEMS = ("pos", "mute", "pin", "pair", "roast_full")
TARGET_ITEMS = ("mute", "pin", "pair", "roast_full")   # нужен ответ на сообщение
PERSONAL_ITEMS = ("vip", "shield")
POS_DAYS, VIP_DAYS, SHIELD_DAYS = 30, 30, 7
MUTE_MIN, PIN_HOURS = 15, 2
TITLE_MAX = 16  # ограничение Telegram на подпись админа

DESCRIPTIONS = {
    "pos": "Настоящая подпись рядом с твоим именем в этом чате, как у админов. Видна в каждом сообщении 30 дней.",
    "mute": f"Человек {MUTE_MIN} минут не сможет писать в чат. Админов и тех, у кого щит, замутить нельзя.",
    "pin": f"Сообщение висит в закрепе {PIN_HOURS} часа.",
    "pair": "Ты и выбранный человек становитесь парой дня в этом чате.",
    "roast_full": "Жёсткая смешная прожарка выбранного человека прямо в чате.",
    "vip": "Корона 👑 в топах и итогах во всех чатах, особое приветствие при входе, итоги без лимита. 30 дней.",
    "shield": "7 дней тебя нельзя замутить и прожарить ни в одном чате.",
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
    """Имя для топов: 👑 у VIP и титул, если есть. {user_id: '👑 Аня · Королева'}."""
    ids = [r["user_id"] for r in rows]
    titles = await db.active_titles(ids)
    vips = await db.vip_ids(ids)
    return {r["user_id"]: ("👑 " if r["user_id"] in vips else "") + r[name_key]
            + (f" · {titles[r['user_id']]}" if r["user_id"] in titles else "") for r in rows}


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
    target_msg = rt.message_id if rt else 0
    lines = ["🛒 <b>Магазин чата</b>", ""]
    buttons = []
    for key in CHAT_ITEMS:
        item = items.get(key)
        if not item:
            continue
        lines.append(f"<b>{esc(item['title'])}</b> · {item['stars']} ⭐\n<i>{esc(item_text(key))}</i>")
        if key in TARGET_ITEMS and not target:
            continue
        if key == "pin" and not rt:
            continue
        link = await bot.create_invoice_link(
            title=item["title"][:32], description=item_text(key)[:255], currency="XTR",
            payload=payload(key, chat["chat_id"], target.id if target and key in TARGET_ITEMS else 0,
                            target_msg if key == "pin" else 0),
            prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])])
        style = "danger" if key in ("mute", "roast_full") else "success" if key == "pos" else "primary"
        who = f" → {target.first_name}" if target and key in ("mute", "pair", "roast_full") else ""
        buttons.append([InlineKeyboardButton(text=f"{item['title']}{who} · {item['stars']} ⭐", url=link, style=style)])
    if not target:
        lines.append("💡 <i>Чтобы купить мут, пару, закреп или прожарку, ответь словом магазин "
                     "на сообщение нужного человека.</i>")
    me = await bot.me()
    buttons.append([InlineKeyboardButton(text="👑 VIP и 🛡 щит: в личке", url=f"https://t.me/{me.username}?start=shop")])
    await say(bot, chat["chat_id"], "\n\n".join(lines), reply_to=message,
              markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def _bot_can(bot: Bot, chat_id: int, right: str) -> bool:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
    except Exception:
        return False
    return me.status == "administrator" and bool(getattr(me, right, False))


async def check(bot: Bot, raw_payload: str, buyer_id: int) -> str | None:
    """Проверка перед оплатой. Строка: почему нельзя купить. None: можно."""
    p = parse_payload(raw_payload)
    item, chat_id, target = p["item"], p.get("chat_id"), p.get("target")
    if item in ("mute", "roast_full") and await shielded(target):
        return "У этого человека щит 🛡, не пробить"
    if item == "mute":
        if not await _bot_can(bot, chat_id, "can_restrict_members"):
            return "У бота нет права ограничивать участников, мут сейчас недоступен"
        try:
            member = await bot.get_chat_member(chat_id, target)
            if member.status in ("administrator", "creator"):
                return "Админа замутить нельзя"
        except Exception:
            return "Не нашёл этого человека в чате"
    if item == "pin" and not await _bot_can(bot, chat_id, "can_pin_messages"):
        return "У бота нет права закреплять сообщения"
    if item == "pos":
        if not await _bot_can(bot, chat_id, "can_promote_members"):
            return "У бота нет права назначать админов, должность сейчас недоступна"
        try:
            member = await bot.get_chat_member(chat_id, buyer_id)
        except Exception:
            return "Сначала зайди в этот чат"
        if member.status == "creator" or (member.status == "administrator"
                                          and not await db.get_chat_title(chat_id, buyer_id)):
            return "Ты уже админ этого чата, подпись тебе ставит владелец чата"
    return None


async def apply(bot: Bot, raw_payload: str, buyer_id: int, buyer_name: str) -> str:
    """Выполняет покупку. Возвращает, что ответить покупателю в личке.
    Для должности возвращает 'ask_title': тогда бот спрашивает текст подписи."""
    p = parse_payload(raw_payload)
    item = p["item"]
    now = time.time()
    perks = await db.get_perks(buyer_id)
    if item == "vip":
        start = max(now, perks["vip_until"] if perks else 0)
        await db.set_perks(buyer_id, vip_until=start + VIP_DAYS * 86400)
        return f"👑 Ты VIP на {VIP_DAYS} дней! Корона уже в топах."
    if item == "shield":
        start = max(now, perks["shield_until"] if perks else 0)
        await db.set_perks(buyer_id, shield_until=start + SHIELD_DAYS * 86400)
        return f"🛡 Щит включён на {SHIELD_DAYS} дней. Тебя не замутить и не прожарить."
    if item.startswith("don"):
        return f"💛 Спасибо за поддержку, {esc(buyer_name)}! Ты в топе донатеров."
    chat_id, target = p["chat_id"], p["target"]
    buyer = mention(buyer_id, buyer_name)
    target_row = await db.get_user(chat_id, target) if target else None
    target_html = mention(target, target_row["name"] if target_row else "кто-то")
    if item == "pos":
        return "ask_title"
    if item == "mute":
        await bot.restrict_chat_member(chat_id, target, permissions=ChatPermissions(can_send_messages=False),
                                       until_date=int(now + MUTE_MIN * 60))
        await say(bot, chat_id, f"🔇 {buyer} купил мут для {target_html} на {MUTE_MIN} минут. Тишина 🤫")
        return f"🔇 Готово, мут на {MUTE_MIN} минут."
    if item == "pin":
        await bot.pin_chat_message(chat_id, p["msg"], disable_notification=True)
        await db.add_pin(chat_id, p["msg"], now + PIN_HOURS * 3600)
        await say(bot, chat_id, f"📌 {buyer} закрепил сообщение на {PIN_HOURS} часа")
        return "📌 Закрепил."
    if item == "pair":
        await db.set_couple(chat_id, db.today(), buyer_id, target)
        await say(bot, chat_id, f"💘 {buyer} купил себе пару дня: {buyer} + {target_html} = ❤️")
        return "💘 Теперь вы пара дня."
    if item == "roast_full":
        await do_full_roast(bot, chat_id, target, buyer_name)
        return "🔥 Жарю в чате!"
    return "Готово."


def clean_title(text: str) -> str | None:
    """Подпись админа в Telegram: до 16 символов и без эмодзи."""
    title = " ".join((text or "").split())
    if not title or len(title) > TITLE_MAX or "http" in title.lower() or "@" in title:
        return None
    if any(ord(ch) > 0xFFFF or 0x2600 <= ord(ch) <= 0x27BF for ch in title):
        return None
    return title


async def give_title(bot: Bot, chat_id: int, user_id: int, name: str, title: str) -> None:
    await bot.promote_chat_member(chat_id, user_id, can_invite_users=True)
    await bot.set_chat_administrator_custom_title(chat_id, user_id, custom_title=title)
    old = await db.get_chat_title(chat_id, user_id)
    start = max(time.time(), old["until"] if old else 0)
    await db.set_chat_title(chat_id, user_id, title, start + POS_DAYS * 86400)
    await say(bot, chat_id, f"🏷 Теперь {mention(user_id, name)} в этом чате носит должность «{esc(title)}»")


async def expire_titles(bot: Bot) -> None:
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
    if not item:
        return await fun.roast(bot, chat, message, author_row)
    target = await fun.roast_target(bot, chat["chat_id"], message)
    if target is None:
        await say(bot, chat["chat_id"], "кого жарить по полной? ответь на его сообщение или назови имя",
                  reply_to=message)
        return
    if await shielded(target["user_id"]):
        await say(bot, chat["chat_id"], f"у {esc(target['name'])} щит 🛡, не пробить", reply_to=message)
        return
    link = await bot.create_invoice_link(
        title="🔥 Прожарка по полной", description=f"Жёсткая прожарка: {target['name']}"[:255], currency="XTR",
        payload=payload("roast_full", chat["chat_id"], target["user_id"]),
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
