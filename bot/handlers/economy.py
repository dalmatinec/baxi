"""Экономика в чате: кошелёк, бонус, магазин за монеты, питомцы, кости и переводы.

Слова в чате (без обращения к боту, работают, если включён тумблер «Монеты и питомцы»):
  кошелёк, бонус, магазин, питомец, покормить, топ питомцев, богачи, топ уровней,
  кости 100 (ответом), передать 100 (ответом), кличка Пушок
Логика в bot/economy/service.py, цифры в bot/economy/catalog.py."""

import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import (BufferedInputFile, CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup,
                           LabeledPrice, Message, User)

from bot import db
from bot.economy import cards, catalog, hooks, service, store
from bot.middlewares import GROUPS
from bot.services import adorders, stars, texts
from bot.services.out import say
from bot.textutil import esc, full_name, mention

log = logging.getLogger(__name__)
router = Router(name="economy")

_TAIL = r"(@\w+)?\s*[!?.]*\s*$"
COMMANDS = [
    ("wallet", re.compile(r"^\s*(кошел[её]к|баланс|мой уровень|/wallet|/me)" + _TAIL, re.I)),
    ("bonus", re.compile(r"^\s*(бонус|/bonus)" + _TAIL, re.I)),
    ("shop", re.compile(r"^\s*(магазин|/shop)" + _TAIL, re.I)),
    ("pet", re.compile(r"^\s*(питомец|мой питомец|/pet)" + _TAIL, re.I)),
    ("feed", re.compile(r"^\s*(покормить|покорми|/feed)" + _TAIL, re.I)),
    ("pets", re.compile(r"^\s*(топ питомцев|питомцы|/pets)" + _TAIL, re.I)),
    ("rich", re.compile(r"^\s*(богачи|топ богачей|топ монет|/rich)" + _TAIL, re.I)),
    ("levels", re.compile(r"^\s*(топ уровней|/levels)" + _TAIL, re.I)),
    ("dice", re.compile(r"^\s*(кости|кубик|/dice)(@\w+)?\s+(\d{1,6})\s*$", re.I)),
    ("dicehelp", re.compile(r"^\s*(/dice|/give)" + _TAIL, re.I)),
    ("gift", re.compile(r"^\s*(передать|перевести|подарить|/give)(@\w+)?\s+(\d{1,6})\s*$", re.I)),
    ("rename", re.compile(r"^\s*(кличка|/petname)(@\w+)?\s+(.{1,30})$", re.I)),
]
MEDALS = ["🥇", "🥈", "🥉"]
PENDING_NAMES: dict[tuple[int, int], int] = {}   # (чат, id сообщения «как назовёшь?») → хозяин питомца
DICE_DELAY = 3.5   # столько крутится кубик в Telegram, ждём, чтобы не спойлерить результат


def match(text: str) -> tuple[str, str] | None:
    for name, rx in COMMANDS:
        m = rx.match(text or "")
        if m:
            return name, (m.group(3) if m.lastindex and m.lastindex >= 3 else "") or ""
    return None


async def eco_filter(message: Message, chat_row=None) -> dict | bool:
    if not hooks.enabled(chat_row) or not message.from_user:
        return False
    found = match(message.text or "")
    return {"eco": found} if found else False


def _name(user: User) -> str:
    return full_name(user.first_name, user.last_name, user.username)


def _kb(rows: list[list[tuple]]) -> InlineKeyboardMarkup:
    """Ряды кнопок: (текст, callback или https-ссылка, стиль)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t, url=d, style=s[0] if s else None) if d.startswith("http") else
        InlineKeyboardButton(text=t, callback_data=d, style=s[0] if s else None) for t, d, *s in row] for row in rows])


def pet_title(pet) -> str:
    """«Пушок · Кошка, 3 ур.», а если клички нет, просто «Кошка, 3 ур.»."""
    info = catalog.PETS[pet["species"]]
    name = f"<b>{esc(pet['name'])}</b> · {info['name']}" if pet["name"] != info["name"] else f"<b>{info['name']}</b>"
    return f"{info['emoji']} {name}, {service.pet_level(pet)} ур."


def _bar(part: float, total: float, width: int = 10) -> str:
    full = max(0, min(width, round(width * part / total))) if total else 0
    return "▰" * full + "▱" * (width - full)


# ---------- экраны ----------

async def wallet_text(chat_id: int, user: User) -> str:
    w = await store.wallet(chat_id, user.id, _name(user))
    lvl = w["level"]
    lo, hi = catalog.xp_for(lvl), catalog.xp_for(lvl + 1)
    pet = await store.pet(chat_id, user.id)
    pet_line = (f"{catalog.PETS[pet['species']]['emoji']} {esc(pet['name'])}, {service.pet_level(pet)} ур., "
                f"сытость {int(service.satiety(pet))}%" if pet else "пока нет, загляни в магазин")
    bonus = "уже забран сегодня ✅" if w["bonus_day"] == service.today() else "ждёт тебя: напиши <b>бонус</b> 🎁"
    return (f"💰 <b>Кошелёк</b> {mention(user.id, _name(user))}\n\n"
            f"🪙 Монеты: <b>{w['coins']}</b>\n"
            f"⭐ Уровень <b>{lvl}</b> · {catalog.title_for(lvl)}\n"
            f"📈 {_bar(w['xp'] - lo, hi - lo)} {w['xp'] - lo}/{hi - lo} опыта\n"
            f"🔥 Серия бонусов: {w['streak']} дн., бонус {bonus}\n"
            f"🐾 Питомец: {pet_line}")


WALLET_KB = _kb([[("🎁 Бонус", "eco:b", "success"), ("🛒 Магазин", "eco:shop", "primary")],
                 [("🐾 Мой питомец", "eco:pet"), ("🏆 Богачи", "eco:rich")]])


async def shop_text(chat_id: int, user: User) -> str:
    w = await store.wallet(chat_id, user.id, _name(user))
    cheapest = min(p["price"] for p in catalog.PETS.values())
    crypto = " или криптой (USDT)" if adorders.can_pay() else ""
    return ("🛒 <b>Магазин чата</b>\n"
            f"Баланс {mention(user.id, _name(user))}: <b>{w['coins']} 🪙</b>\n\n"
            f"✨ <b>Свой ник навсегда</b> · {catalog.NICK_PRICE} 🪙\n"
            "<i>Премиум-эмодзи и жирный ник у имени везде, где бот тебя упоминает: топы, итоги, игры. "
            "Любой шрифт, какой пришлёшь.</i>\n\n"
            f"🐾 <b>Питомцы</b>: {len(catalog.PETS)} видов, от {cheapest} 🪙\n"
            "<i>От улитки до дракона. У каждого своя еда, кто сильнее, тот выше в топе питомцев.</i>\n\n"
            f"💳 <b>Пополнить монеты</b> звёздами Telegram{crypto}\n\n"
            "💡 Монеты дают за сообщения в чате (не чаще 2 раз в минуту), бонус дня и победы в костях.")


SHOP_KB = _kb([[("✨ Ник навсегда", "eco:nick", "success"), ("🐾 Питомцы", "eco:ps", "primary")],
               [("💳 Пополнить", "eco:top", "success"), ("💰 Кошелёк", "eco:w")]])


def pet_shop() -> tuple[str, InlineKeyboardMarkup]:
    """Все питомцы за монеты, по два в ряд."""
    lines = ["🐾 <b>Питомцы</b>", "<i>Покупка заменяет текущего питомца на более крутого. Цена · сила · еда</i>", ""]
    buttons = []
    for key in catalog.PET_ORDER:
        p = catalog.PETS[key]
        food = p["food"]
        lines.append(f"{p['emoji']} <b>{p['name']}</b> · {p['price']} 🪙 · 💪 {p['power']} · {food[1]} {food[2]} 🪙")
        buttons.append((f"{p['emoji']} {p['name']} · {p['price']}", f"eco:pb:{key}"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return "\n".join(lines), _kb(rows + [[("⬅️ Магазин", "eco:shop")]])


async def topup(bot: Bot, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    items = await stars.items_map()
    buttons, row = [], []
    for key, (coins, *_) in catalog.COIN_PACKS.items():
        item = items.get(key)
        if not item:
            continue
        link = await bot.create_invoice_link(
            title=item["title"][:32], description=stars.item_text(key)[:255], currency="XTR",
            payload=stars.payload(key, chat_id), prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])])
        row.append((f"🪙 {coins} · {item['stars']} ⭐", link, "success"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    crypto = ""
    if adorders.can_pay():
        me = await bot.me()
        buttons.append([("💎 Оплатить криптой (USDT)", f"https://t.me/{me.username}?start=coins{chat_id}", "primary")])
        crypto = "\n💎 Криптой: откроется личка бота, там выбор суммы и адрес для оплаты USDT (TON или TRC20)."
    buttons.append([("⬅️ Магазин", "eco:shop")])
    return ("💳 <b>Пополнить монеты</b>\n\n⭐ Звёздами: жми на сумму, монеты придут на твой кошелёк в этом чате "
            f"сразу после оплаты. Платит и получает тот, кто нажал.{crypto}"), _kb(buttons)


async def send_pet(bot: Bot, chat, user: User, reply_to: Message | None = None) -> None:
    chat_id = chat["chat_id"]
    pet = await store.pet(chat_id, user.id)
    if not pet:
        await say(bot, chat_id, f"🐾 {mention(user.id, _name(user))}, у тебя пока нет питомца. Выбирай!",
                  reply_to=reply_to, markup=_kb([[("🐾 Выбрать питомца", "eco:ps", "success")]]))
        return
    sat, lvl, power = service.satiety(pet), service.pet_level(pet), service.pet_power(pet)
    caption = (f"{pet_title(pet)}\n"
               f"Хозяин: {mention(user.id, _name(user))}\n"
               f"🍖 Сытость {int(sat)}% · 💪 сила {power}"
               + (f"\n🕓 Последний раз кормил: {esc(pet['fed_by'])}" if pet["fed_by"] else "")
               + ("\n😿 Голодный питомец не растёт, покорми его" if sat < catalog.PET_XP_HUNGRY else ""))
    kb = hooks.feed_kb(user.id, pet["species"])
    image = await asyncio.to_thread(cards.pet_card, pet, sat, lvl, power, _name(user), chat["bot_name"])
    if image is None:
        await say(bot, chat_id, caption, reply_to=reply_to, markup=kb)
        return
    from bot.services.out import reply_params
    await bot.send_photo(chat_id, BufferedInputFile(image, "pet.jpg"), caption=caption, parse_mode="HTML",
                         reply_markup=kb, reply_parameters=reply_params(reply_to))


async def pets_top_text(chat_id: int) -> str:
    rows = await service.pet_top(chat_id)
    if not rows:
        return "🐾 <b>Топ питомцев</b>\n\nПока ни у кого нет питомца. Первый будет сразу первым 👀 Напиши: магазин"
    lines = ["🐾 <b>Топ питомцев</b>", ""]
    for i, p in enumerate(rows):
        place = MEDALS[i] if i < 3 else f"{i + 1}."
        lines.append(f"{place} {pet_title(p)} · {mention(p['user_id'], p['owner'])} · 💪 {service.pet_power(p)}")
    return "\n".join(lines)


async def top_text(chat_id: int, kind: str) -> str:
    rows = await (store.rich_top(chat_id) if kind == "rich" else store.level_top(chat_id))
    title = "🏆 <b>Богачи чата</b>" if kind == "rich" else "⭐ <b>Топ уровней</b>"
    if not rows:
        return f"{title}\n\nПока пусто. Пишите в чат, монеты и опыт капают сами."
    lines = [title, ""]
    for i, r in enumerate(rows):
        place = MEDALS[i] if i < 3 else f"{i + 1}."
        value = f"{r['coins']} 🪙" if kind == "rich" else f"{r['level']} ур. · {catalog.title_for(r['level'])}"
        lines.append(f"{place} {mention(r['user_id'], r['name'])}: <b>{value}</b>")
    return "\n".join(lines)


async def bonus_text(chat_id: int, user: User) -> str:
    got = await service.claim_bonus(chat_id, user.id, _name(user))
    if not got:
        return f"🎁 {mention(user.id, _name(user))}, бонус уже забран сегодня. Приходи завтра, серия растёт!"
    amount, streak = got
    nxt = min(catalog.BONUS_BASE + catalog.BONUS_STEP * streak, catalog.BONUS_MAX)
    return await texts.render("eco_bonus", кто=mention(user.id, _name(user)), сколько=amount, серия=streak, завтра=nxt)


# ---------- команды словами ----------

@router.message(F.chat.type.in_(GROUPS), F.text, eco_filter)
async def on_eco(message: Message, bot: Bot, eco: tuple[str, str], chat_row) -> None:
    name, arg = eco
    chat_id, user = message.chat.id, message.from_user
    try:
        if name == "wallet":
            await say(bot, chat_id, await wallet_text(chat_id, user), reply_to=message, markup=WALLET_KB)
        elif name == "bonus":
            await say(bot, chat_id, await bonus_text(chat_id, user), reply_to=message)
        elif name == "shop":
            await say(bot, chat_id, await shop_text(chat_id, user), reply_to=message, markup=SHOP_KB)
        elif name == "pet":
            await send_pet(bot, chat_row, user, message)
        elif name == "feed":
            pet = await store.pet(chat_id, user.id)
            if not pet:
                await say(bot, chat_id, "у тебя пока нет питомца", reply_to=message,
                          markup=_kb([[("🐾 Выбрать питомца", "eco:ps", "success")]]))
            else:
                await say(bot, chat_id, f"Чем покормить {esc(pet['name'])}? Сытость {int(service.satiety(pet))}%",
                          reply_to=message, markup=hooks.feed_kb(user.id, pet["species"]))
        elif name == "pets":
            await say(bot, chat_id, await pets_top_text(chat_id), reply_to=message)
        elif name in ("rich", "levels"):
            await say(bot, chat_id, await top_text(chat_id, name), reply_to=message)
        elif name == "rename":
            why = await service.rename_pet(chat_id, user.id, arg)
            await say(bot, chat_id, why or f"✅ Теперь твоего питомца зовут <b>{esc(arg.strip()[:20])}</b>",
                      reply_to=message)
        elif name == "dicehelp":
            await say(bot, chat_id, "🎲 Кости: ответь на сообщение соперника <b>кости 100</b> (ставка в монетах).\n"
                                    "💸 Перевод: ответь <b>передать 100</b>.", reply_to=message)
        elif name in ("dice", "gift"):
            await _with_target(bot, message, name, int(arg))
    except Exception:
        log.exception("Экономика: команда %s в чате %s не выполнилась", name, chat_id)


async def _with_target(bot: Bot, message: Message, name: str, amount: int) -> None:
    """Кости и переводы: работают только ответом на сообщение живого человека."""
    chat_id, user = message.chat.id, message.from_user
    rt = message.reply_to_message
    target = rt.from_user if rt and rt.from_user and not rt.from_user.is_bot and not rt.forum_topic_created else None
    if not target:
        hint = "кости 100" if name == "dice" else "передать 100"
        await say(bot, chat_id, f"напиши <b>{hint}</b> ответом на сообщение того, с кем {'играть' if name == 'dice' else 'делиться'}",
                  reply_to=message)
        return
    a_name, b_name = _name(user), _name(target)
    if name == "gift":
        why = await service.gift(chat_id, user.id, a_name, target.id, b_name, amount)
        text = why or await texts.render("eco_gift", от=mention(user.id, a_name), кому=mention(target.id, b_name),
                                         сколько=amount)
        await say(bot, chat_id, text, reply_to=message)
        return
    why = await service.start_duel(chat_id, user.id, a_name, target.id, b_name, amount)
    if why:
        await say(bot, chat_id, why, reply_to=message)
        return
    text = await texts.render("eco_dice_call", от=mention(user.id, a_name), кому=mention(target.id, b_name),
                              ставка=amount)
    await say(bot, chat_id, text, reply_to=message,
              markup=_kb([[("✅ Принять", "eco:da", "success"), ("🏳 Сдаться", "eco:dd", "danger")]]))


# ---------- кличка нового питомца: ответом на вопрос бота ----------

async def ask_name(bot: Bot, chat_id: int, user: User, species: str) -> None:
    info = catalog.PETS[species]
    text = await texts.render("eco_new_pet", кто=mention(user.id, _name(user)), вид=info["name"], эмодзи=info["emoji"])
    sent = await say(bot, chat_id, text, markup=ForceReply(selective=True, input_field_placeholder="Кличка питомца"))
    if sent:
        PENDING_NAMES[(chat_id, sent.message_id)] = user.id
        if len(PENDING_NAMES) > 2000:
            PENDING_NAMES.pop(next(iter(PENDING_NAMES)))


def naming_filter(message: Message) -> bool:
    rt = message.reply_to_message
    return bool(rt and message.from_user and PENDING_NAMES.get((message.chat.id, rt.message_id)) == message.from_user.id)


@router.message(F.chat.type.in_(GROUPS), F.text, naming_filter)
async def on_pet_name(message: Message, bot: Bot, chat_row) -> None:
    chat_id, user = message.chat.id, message.from_user
    why = await service.rename_pet(chat_id, user.id, message.text)
    if why:
        await say(bot, chat_id, f"{why}. Попробуй ещё раз ответом на мой вопрос", reply_to=message)
        return
    PENDING_NAMES.pop((chat_id, message.reply_to_message.message_id), None)
    await send_pet(bot, chat_row, user, message)


# ---------- кубики от участников ----------

@router.message(F.chat.type.in_(GROUPS), F.dice)
async def on_dice(message: Message, bot: Bot) -> None:
    """Считаются только 🎲 от двух игроков и по очереди. Чужие и пересланные кубики игнорируются."""
    if message.dice.emoji != "🎲" or message.forward_origin or not message.from_user:
        return
    chat_id = message.chat.id
    value = message.dice.value
    result, d = await service.roll(chat_id, message.from_user.id, value)
    if not result:
        return
    await asyncio.sleep(DICE_DELAY)
    a, b = mention(d.a, d.a_name), mention(d.b, d.b_name)
    if result == "wait":
        text = f"{a} выбросил <b>{value}</b>. Теперь {b}, кидай 🎲"
    elif result == "tie":
        text = f"🤝 Ничья {value}:{value}! Перебрасываем, {a} снова первый 🎲"
    else:
        va, vb = d.rolls[d.a], d.rolls[d.b]
        win_id, win_name = (d.a, d.a_name) if va > vb else (d.b, d.b_name)
        text = await texts.render("eco_dice_win", победитель=mention(win_id, win_name), банк=d.bet * 2,
                                  первый=a, очки1=va, второй=b, очки2=vb)
    await say(bot, chat_id, text, reply_to=message)


# ---------- кнопки ----------

@router.callback_query(F.data.startswith("eco:"))
async def on_button(cb: CallbackQuery, bot: Bot) -> None:
    """Кнопки работают для того, кто нажал: его кошелёк, его питомец, его покупка."""
    if not cb.message or cb.message.chat.type not in GROUPS:
        return await cb.answer()
    chat = await db.get_chat(cb.message.chat.id)
    if not hooks.enabled(chat) or not chat["approved"]:
        return await cb.answer("монеты и питомцы в этом чате выключены", show_alert=True)
    parts = cb.data.split(":")
    action, chat_id, user = parts[1], chat["chat_id"], cb.from_user
    try:
        await _button(bot, cb, chat, chat_id, user, action, parts)
    except Exception:
        log.exception("Экономика: кнопка %s в чате %s", cb.data, chat_id)
        await cb.answer("что-то пошло не так, попробуй ещё раз", show_alert=True)


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    await cb.answer()
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)


async def _button(bot: Bot, cb: CallbackQuery, chat, chat_id: int, user: User, action: str, parts: list[str]) -> None:
    if action == "w":
        await cb.answer()
        await say(bot, chat_id, await wallet_text(chat_id, user), markup=WALLET_KB)
    elif action == "b":
        await cb.answer()
        await say(bot, chat_id, await bonus_text(chat_id, user))
    elif action == "shop":
        text = await shop_text(chat_id, user)
        if cb.message.text:
            await _edit(cb, text, SHOP_KB)
        else:  # нажали под картинкой: картинку текстом не заменить, шлём новое сообщение
            await cb.answer()
            await say(bot, chat_id, text, markup=SHOP_KB)
    elif action == "ps":
        text, kb = pet_shop()
        if cb.message.text:
            await _edit(cb, text, kb)
        else:
            await cb.answer()
            await say(bot, chat_id, text, markup=kb)
    elif action == "top":
        text, kb = await topup(bot, chat_id)
        await _edit(cb, text, kb)
    elif action == "pet":
        await cb.answer()
        await send_pet(bot, chat, user)
    elif action == "rich":
        await cb.answer()
        await say(bot, chat_id, await top_text(chat_id, "rich"))
    elif action == "pb":   # выбрал питомца: спрашиваем подтверждение, чтобы случайно не потратить монеты
        species = parts[2]
        info = catalog.PETS.get(species)
        if not info:
            return await cb.answer()
        current = await store.pet(chat_id, user.id)
        if current and catalog.PET_ORDER.index(current["species"]) >= catalog.PET_ORDER.index(species):
            return await cb.answer("у тебя уже такой питомец или круче", show_alert=True)
        coins = (await store.wallet(chat_id, user.id, _name(user)))["coins"]
        if coins < info["price"]:
            return await cb.answer(f"нужно {info['price']} 🪙, у тебя {coins}", show_alert=True)
        await cb.answer()
        swap = f"\nТвой {esc(current['name'])} уйдёт, новый начнёт с 1 уровня." if current else ""
        await say(bot, chat_id, f"{info['emoji']} {mention(user.id, _name(user))}, взять <b>{info['name']}</b> за "
                                f"<b>{info['price']} 🪙</b>?{swap}",
                  markup=_kb([[("✅ Купить", f"eco:pk:{species}:{user.id}", "success"), ("Отмена", f"eco:nx:{user.id}")]]))
    elif action == "pk":
        species, owner = parts[2], int(parts[3])
        if owner != user.id:
            return await cb.answer("это не твоя покупка", show_alert=True)
        why = await service.buy_pet(chat_id, user.id, _name(user), species)
        if why:
            return await cb.answer(why, show_alert=True)
        info = catalog.PETS[species]
        await cb.answer(f"{info['emoji']} {info['name']} теперь твой!")
        try:
            await cb.message.delete()
        except Exception:
            pass
        await ask_name(bot, chat_id, user, species)
    elif action == "f":
        owner_id, kind = int(parts[2]), parts[3]
        res = await service.feed(chat_id, owner_id, user.id, _name(user), kind)
        if "error" in res:
            return await cb.answer(res["error"], show_alert=True)
        food, pet = res["food"], res["pet"]
        await cb.answer(f"{food['emoji']} Ням! Сытость {res['satiety']}%")
        whose = "" if owner_id == user.id else f" (питомец {mention(owner_id, pet['owner'])})"
        await say(bot, chat_id, await texts.render(
            "eco_feed", кто=mention(user.id, _name(user)), питомец=f"<b>{esc(pet['name'])}</b>{whose}",
            корм=food["name"], еда=food["emoji"], цена=food["price"], сытость=res["satiety"]))
    elif action == "nick":
        await cb.answer()
        await say(bot, chat_id, f"✨ {mention(user.id, _name(user))}, купить свой ник навсегда за "
                                f"<b>{catalog.NICK_PRICE} 🪙</b>? После покупки настроишь эмодзи и ник в личке бота.",
                  markup=_kb([[("✅ Купить", f"eco:nk:{user.id}", "success"), ("Отмена", f"eco:nx:{user.id}")]]))
    elif action in ("nk", "nx"):
        if int(parts[2]) != user.id:
            return await cb.answer("это не твоя покупка", show_alert=True)
        if action == "nx":
            await cb.answer()
            return await cb.message.delete()
        why = await service.buy_look(chat_id, user.id)
        if why:
            return await cb.answer(why, show_alert=True)
        await stars.refresh_looks()
        me = await bot.me()
        await _edit(cb, f"✨ {mention(user.id, _name(user))} купил свой ник навсегда! Теперь настрой его в личке: "
                        "пришли премиум-эмодзи и ник любым шрифтом.",
                    _kb([[("✏️ Настроить ник", f"https://t.me/{me.username}?start=nick", "success")]]))
    elif action in ("da", "dd"):
        await _duel_button(bot, cb, chat_id, user, action)
    else:
        await cb.answer()


async def _duel_button(bot: Bot, cb: CallbackQuery, chat_id: int, user: User, action: str) -> None:
    if action == "da":
        why = await service.accept_duel(chat_id, user.id)
        if why:
            return await cb.answer(why, show_alert=True)
        d = service.active_duel(chat_id)
        await _edit(cb, await texts.render("eco_dice_go", банк=d.bet * 2, первый=mention(d.a, d.a_name),
                                           второй=mention(d.b, d.b_name)),
                    _kb([[("🏳 Сдаться", "eco:dd", "danger")]]))
        return
    result, d = await service.give_up(chat_id, user.id)
    if not result:
        return await cb.answer("ты не участвуешь в этой игре", show_alert=True)
    loser = mention(user.id, d.a_name if user.id == d.a else d.b_name)
    if result == "cancel":
        await _edit(cb, f"🏳 {loser} отказался от игры. Ставка не списана.", None)
    else:
        win_id, win_name = (d.b, d.b_name) if user.id == d.a else (d.a, d.a_name)
        await _edit(cb, f"🏳 {loser} сдался. {mention(win_id, win_name)} забирает <b>{d.bet * 2} 🪙</b>", None)


# ---------- пополнение монет криптой (USDT) в личке, через те же счета, что и реклама ----------

async def crypto_menu(message: Message, chat_id: int) -> None:
    """Открыли личку по кнопке «Оплатить криптой» из чата: выбор пачки монет."""
    chat = await db.get_chat(chat_id)
    if not chat or not adorders.can_pay():
        await message.answer("Оплата криптой сейчас недоступна. Пополнить можно звёздами прямо в чате: напиши там магазин.")
        return
    rows = [[(f"🪙 {coins} монет · {usd} USDT", f"ecc:{chat_id}:{key}", "success")]
            for key, (coins, _, usd) in catalog.COIN_PACKS.items()]
    await message.answer(f"💎 <b>Пополнить монеты криптой</b>\n\nЧат: <b>{esc(chat['title'] or '')}</b>\n"
                         "Монеты придут на твой кошелёк в этом чате, как только оплата дойдёт. Выбери сумму:",
                         parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("ecc:"))
async def on_crypto_pack(cb: CallbackQuery, bot: Bot) -> None:
    _, chat_id, key = cb.data.split(":")
    pack = catalog.COIN_PACKS.get(key)
    if not pack or not adorders.can_pay():
        return await cb.answer("недоступно", show_alert=True)
    user = cb.from_user
    name = _name(user) + (f" @{user.username}" if user.username else "")
    oid = await db.create_order(user.id, name, "coins", f"🪙 {pack[0]} монет", pack[2], pack[0], "", "", "", [],
                                "awaiting", target=int(chat_id))
    await cb.answer()
    await adorders.start_payment(bot, oid)
