"""Экономика в чате: короткий кошелёк, бонус, питомец и корм, топы, кости и переводы.
Магазин и полный профиль в личке бота (profile.py), отсюда на них ведут кнопки.

Слова в чате (работают, если включён тумблер «Монеты и питомцы»):
  кошелёк, бонус, магазин, профиль, питомец, покормить, топ питомцев, богачи, топ уровней,
  кости 100 (ответом), передать 100 (ответом), кличка Пушок"""

import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message, User

from bot import db
from bot.economy import hooks, service, store
from bot.handlers.economy.common import (card_allowed, kb, name_of, pets_top_text, send_pet, short_wallet,
                                         top_text)
from bot.middlewares import GROUPS
from bot.services import texts
from bot.services.out import say
from bot.textutil import esc, mention

log = logging.getLogger(__name__)
router = Router(name="economy_chat")

_TAIL = r"(@\w+)?\s*[!?.]*\s*$"
COMMANDS = [
    ("wallet", re.compile(r"^\s*(кошел[её]к|баланс|мой уровень|/wallet|/me)" + _TAIL, re.I)),
    ("profile", re.compile(r"^\s*(профиль|мой профиль|магазин|/shop|/profile)" + _TAIL, re.I)),
    ("bonus", re.compile(r"^\s*(бонус|/bonus)" + _TAIL, re.I)),
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


async def dm_link(bot: Bot, payload: str = "profile") -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start={payload}"


async def profile_kb(bot: Bot, text: str = "👤 Профиль и магазин"):
    return kb([[(text, await dm_link(bot), "success")]])


SHOP_HINT = ("🛒 Магазин у каждого свой, в личке бота: профиль, монеты, питомцы, ник навсегда и пополнение. "
             "Монеты общие во всех чатах.")


# ---------- команды словами ----------

@router.message(F.chat.type.in_(GROUPS), F.text, eco_filter)
async def on_eco(message: Message, bot: Bot, eco: tuple[str, str], chat_row) -> None:
    name, arg = eco
    chat_id, user = message.chat.id, message.from_user
    try:
        if name == "wallet":
            await say(bot, chat_id, await short_wallet(user), reply_to=message, markup=await profile_kb(bot))
        elif name == "profile":
            await say(bot, chat_id, SHOP_HINT, reply_to=message, markup=await profile_kb(bot, "🛒 Открыть в личке"))
        elif name == "bonus":
            await say(bot, chat_id, await bonus_text(user), reply_to=message)
        elif name == "pet":
            await show_pet(bot, chat_row, user, message)
        elif name == "feed":
            pet = await store.pet(user.id)
            if not pet:
                await say(bot, chat_id, "у тебя пока нет питомца, завести можно в личке бота", reply_to=message,
                          markup=await profile_kb(bot, "🐾 Завести питомца"))
            else:
                await say(bot, chat_id, f"Чем покормить {esc(pet['name'])}? Сытость {int(service.satiety(pet))}%",
                          reply_to=message, markup=hooks.feed_kb(user.id, pet["species"]))
        elif name == "pets":
            await say(bot, chat_id, await pets_top_text(chat_id), reply_to=message)
        elif name in ("rich", "levels"):
            await say(bot, chat_id, await top_text(chat_id, name), reply_to=message)
        elif name == "rename":
            why = await service.rename_pet(user.id, arg)
            await say(bot, chat_id, why or f"✅ Теперь твоего питомца зовут <b>{esc(service.clean_pet_name(arg))}</b>",
                      reply_to=message)
        elif name == "dicehelp":
            await say(bot, chat_id, "🎲 Кости: ответь на сообщение соперника <b>кости 100</b> (ставка в монетах).\n"
                                    "💸 Перевод: ответь <b>передать 100</b>.", reply_to=message)
        elif name in ("dice", "gift"):
            await _with_target(bot, message, name, int(arg))
    except Exception:
        log.exception("Экономика: команда %s в чате %s не выполнилась", name, chat_id)


async def bonus_text(user: User) -> str:
    got = await service.claim_bonus(user.id, name_of(user))
    if not got:
        return f"🎁 {mention(user.id, name_of(user))}, бонус уже забран сегодня. Приходи завтра, серия растёт!"
    amount, streak = got
    level = (await store.wallet(user.id))["level"]
    return await texts.render("eco_bonus", кто=mention(user.id, name_of(user)), сколько=amount, серия=streak,
                              завтра=service.next_bonus(streak, level))


async def show_pet(bot: Bot, chat, user: User, reply_to: Message | None = None) -> None:
    if not card_allowed(chat["chat_id"], user.id):
        return
    if not await send_pet(bot, chat["chat_id"], user, chat["bot_name"], reply_to):
        await say(bot, chat["chat_id"], f"🐾 {mention(user.id, name_of(user))}, у тебя пока нет питомца. "
                                        "Выбрать можно в личке бота: от улитки до дракона.",
                  reply_to=reply_to, markup=await profile_kb(bot, "🐾 Выбрать питомца"))


async def _with_target(bot: Bot, message: Message, name: str, amount: int) -> None:
    """Кости и переводы: работают только ответом на сообщение живого человека."""
    chat_id, user = message.chat.id, message.from_user
    rt = message.reply_to_message
    target = rt.from_user if rt and rt.from_user and not rt.from_user.is_bot and not rt.forum_topic_created else None
    if not target:
        hint = "кости 100" if name == "dice" else "передать 100"
        whom = "играть" if name == "dice" else "делиться"
        await say(bot, chat_id, f"напиши <b>{hint}</b> ответом на сообщение того, с кем {whom}", reply_to=message)
        return
    a_name, b_name = name_of(user), name_of(target)
    if name == "gift":
        why = await service.gift(user.id, a_name, target.id, b_name, amount)
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
              markup=kb([[("✅ Принять", "eco:da", "success"), ("🏳 Сдаться", "eco:dd", "danger")]]))


# ---------- кубики от участников ----------

@router.message(F.chat.type.in_(GROUPS), F.dice)
async def on_dice(message: Message, bot: Bot) -> None:
    """Считаются только 🎲 от двух игроков и по очереди. Чужие и пересланные кубики игнорируются."""
    if message.dice.emoji != "🎲" or message.forward_origin or not message.from_user:
        return
    chat_id, value = message.chat.id, message.dice.value
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


# ---------- кнопки в чате ----------

@router.callback_query(F.data.startswith("eco:"))
async def on_button(cb: CallbackQuery, bot: Bot) -> None:
    """Кнопки работают для того, кто нажал: его кошелёк, его питомец, его игра."""
    if not cb.message or cb.message.chat.type not in GROUPS:
        return await cb.answer()
    chat = await db.get_chat(cb.message.chat.id)
    if not hooks.enabled(chat) or not chat["approved"]:
        return await cb.answer("монеты и питомцы в этом чате выключены", show_alert=True)
    action, chat_id, user = cb.data.split(":")[1], chat["chat_id"], cb.from_user
    try:
        if action == "w":
            await cb.answer()
            await say(bot, chat_id, await short_wallet(user), markup=await profile_kb(bot))
        elif action == "b":
            await cb.answer()
            await say(bot, chat_id, await bonus_text(user))
        elif action == "shop":
            await cb.answer()
            await say(bot, chat_id, SHOP_HINT, markup=await profile_kb(bot, "🛒 Открыть в личке"))
        elif action == "pet":
            await cb.answer()
            await show_pet(bot, chat, user)
        elif action == "rich":
            await cb.answer()
            await say(bot, chat_id, await top_text(chat_id, "rich"))
        elif action in ("da", "dd"):
            await _duel_button(cb, chat_id, user, action)
        else:
            await cb.answer()
    except Exception:
        log.exception("Экономика: кнопка %s в чате %s", cb.data, chat_id)
        await cb.answer("что-то пошло не так, попробуй ещё раз", show_alert=True)


async def _edit(cb: CallbackQuery, text: str, markup=None) -> None:
    await cb.answer()
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _duel_button(cb: CallbackQuery, chat_id: int, user: User, action: str) -> None:
    if action == "da":
        why = await service.accept_duel(chat_id, user.id)
        if why:
            return await cb.answer(why, show_alert=True)
        d = service.active_duel(chat_id)
        await _edit(cb, await texts.render("eco_dice_go", банк=d.bet * 2, первый=mention(d.a, d.a_name),
                                           второй=mention(d.b, d.b_name)),
                    kb([[("🏳 Сдаться", "eco:dd", "danger")]]))
        return
    result, d = await service.give_up(chat_id, user.id)
    if not result:
        return await cb.answer("ты не участвуешь в этой игре", show_alert=True)
    loser = mention(user.id, d.a_name if user.id == d.a else d.b_name)
    if result == "cancel":
        await _edit(cb, f"🏳 {loser} отказался от игры. Ставка не списана.")
    else:
        win_id, win_name = (d.b, d.b_name) if user.id == d.a else (d.a, d.a_name)
        await _edit(cb, f"🏳 {loser} сдался. {mention(win_id, win_name)} забирает <b>{d.bet * 2} 🪙</b>")


# ---------- корм: кнопки под карточкой питомца, в чате и в личке ----------

@router.callback_query(F.data.startswith("ef:"))
async def on_feed(cb: CallbackQuery, bot: Bot) -> None:
    """Покормить: платит тот, кто нажал. Можно кормить и чужого питомца, бот пишет кто и чем."""
    _, owner_id, kind = cb.data.split(":")
    owner_id, user = int(owner_id), cb.from_user
    res = await service.feed(owner_id, user.id, name_of(user), kind)
    if "error" in res:
        return await cb.answer(res["error"], show_alert=True)
    food, pet = res["food"], res["pet"]
    sale = f" (скидка ранга {food['discount']}%)" if food.get("discount") else ""
    await cb.answer(f"{food['emoji']} Ням! Сытость {res['satiety']}%{sale}")
    whose = "" if owner_id == user.id else f" · хозяин {mention(owner_id, pet['owner'])}"
    text = await texts.render("eco_feed", кто=mention(user.id, name_of(user)),
                              питомец=f"<b>{esc(pet['name'])}</b>{whose}", корм=food["name"], еда=food["emoji"],
                              цена=food["price"], сытость=res["satiety"])
    await say(bot, cb.message.chat.id, text)
