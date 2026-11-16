"""Админка → Люди: найти человека по @username или id, посмотреть, где он, сколько задонатил,
выдать VIP или щит, написать ему."""

import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.services import stars
from bot.services.approval import until_text
from bot.textutil import esc

router = Router(name="admin-people")


class PeopleFind(StatesGroup):
    query = State()


@router.callback_query(F.data == "ppl:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PeopleFind.query)
    top = await db.donors_top(5)
    lines = [f"• {esc(r['name'])}: {r['stars']} ⭐" for r in top] if top else []
    await show(cb, "👥 <b>Люди</b>\n\nПришли @username или id человека, покажу всё о нём: в каких чатах, "
                   "сколько задонатил, VIP и щит."
               + ("\n\n<b>Топ донатеров:</b>\n" + "\n".join(lines) if lines else ""),
               kb([[("🧠 Стереть заметки о людях во всех чатах", "ppl:nzall")], [BACK_MENU]]))


async def person_card(target, uid: int) -> None:
    p = await db.find_person(str(uid))
    if not p:
        return await show(target, "Не нашёл такого человека.", kb([[("🔎 Искать ещё", "ppl:menu"), BACK_MENU]]))
    perks = await db.get_perks(uid)
    now = time.time()
    vip = perks["vip_until"] if perks and perks["vip_until"] > now else 0
    shield = perks["shield_until"] if perks and perks["shield_until"] > now else 0
    user = f" @{esc(p['username'])}" if p["username"] else ""
    chats = ", ".join(esc(t) for t in p["chats"][:10]) or "нет"
    text = (f"👤 <a href=\"tg://user?id={uid}\">{esc(p['name'] or 'без имени')}</a>{user}\n<code>{uid}</code>\n\n"
            f"💬 Чаты: {chats}\n📨 Личка с ботом: {'да' if p['dm'] else 'нет'}\n"
            f"⭐ Задонатил: {p['stars']} ⭐\n"
            f"👑 VIP: {'до ' + until_text(vip) if vip else 'нет'}\n🛡 Щит: {'до ' + until_text(shield) if shield else 'нет'}")
    notes = await db.notes_of(uid)
    if notes:
        text += "\n\n🧠 <b>Что бот о нём помнит:</b>\n" + "\n".join(
            f"• <i>{esc(n['title'] or 'чат')[:30]}</i>: {esc(n['notes'])}" for n in notes[:6])
    rows = [[("✍️ Написать через бота", f"sup:{uid}", "primary")]]
    if p["username"]:
        rows.append([(f"💬 @{p['username']} напрямую", f"https://t.me/{p['username']}")])
    rows += [[("👑 VIP +30 дн", f"ppl:vip:{uid}", "success"), ("🛡 Щит +7 дн", f"ppl:sh:{uid}")],
             [("❌ Снять VIP и щит", f"ppl:off:{uid}", "danger")] if vip or shield else [],
             [("🧠 Стереть, что бот о нём помнит", f"ppl:nz:{uid}")] if notes else [],
             [("🔎 Искать ещё", "ppl:menu"), BACK_MENU]]
    await show(target, text, kb(rows))


@router.message(PeopleFind.query, F.text)
async def on_query(message: Message, state: FSMContext) -> None:
    p = await db.find_person(message.text)
    if not p:
        return await message.answer("Не нашёл. Пришли @username или id ещё раз или /cancel.")
    await state.clear()
    await person_card(message, p["user_id"])


@router.callback_query(F.data.startswith("ppl:nz:"))
async def cb_clear_person_notes(cb: CallbackQuery) -> None:
    uid = int(cb.data.split(":")[2])
    n = await db.clear_notes(user_id=uid)
    await cb.answer(f"🧠 Стёр заметки ({n}). Бот узнает его заново через 20 сообщений", show_alert=True)
    await person_card(cb, uid)


@router.callback_query(F.data.in_({"ppl:nzall", "ppl:NZALL"}))
async def cb_clear_all_notes(cb: CallbackQuery, state: FSMContext) -> None:
    """Стереть все заметки о людях во всех чатах (с подтверждением)."""
    if cb.data == "ppl:nzall":
        await cb.answer()
        return await show(cb, "🧠 <b>Стереть заметки о людях во всех чатах?</b>\n\nБот забудет, что знал о людях "
                              "(имена, увлечения, кто откуда), и узнает их заново по новым правилам: первая заметка "
                              "через 20 сообщений человека. История переписки, ранги, монеты и репутация останутся.",
                          kb([[("Нет", "ppl:menu")], [("🧠 Да, стереть", "ppl:NZALL", "danger")]]))
    n = await db.clear_notes()
    await cb.answer(f"Стёр заметки: {n}", show_alert=True)
    await cb_menu(cb, state)


@router.callback_query(F.data.startswith(("ppl:vip:", "ppl:sh:", "ppl:off:")))
async def cb_perk(cb: CallbackQuery) -> None:
    _, op, uid = cb.data.split(":")
    uid = int(uid)
    perks = await db.get_perks(uid)
    now = time.time()
    if op == "vip":
        start = max(now, perks["vip_until"] if perks else 0)
        await db.set_perks(uid, vip_until=start + 30 * 86400)
        await cb.answer("👑 VIP выдан")
    elif op == "sh":
        start = max(now, perks["shield_until"] if perks else 0)
        await db.set_perks(uid, shield_until=start + 7 * 86400)
        await cb.answer("🛡 Щит выдан")
    else:
        await db.set_perks(uid, vip_until=0, shield_until=0)
        await cb.answer("Снято")
    await stars.refresh_looks()
    await person_card(cb, uid)
