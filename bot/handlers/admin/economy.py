"""Админка → Экономика: цифры по монетам и питомцам, выдача монет людям (сразу многим) и тесты на себе.

Тесты нужны, чтобы проверить всё руками: накрутить себе монет, сбросить бонус, сделать питомца голодным
(бот напишет в личку через минуту), убрать питомца и купить заново."""

import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.economy import catalog, store
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.textutil import esc

router = Router(name="admin-economy")


class GiveCoins(StatesGroup):
    who = State()
    amount = State()


async def _menu(target, user_id: int) -> None:
    t = await store.totals()
    w = await store.wallet(user_id)
    pet = await store.pet(user_id)
    pet_line = f"{catalog.PETS[pet['species']]['emoji']} {esc(pet['name'])}" if pet else "нет"
    await show(target, "💰 <b>Экономика</b>\n\n"
                       f"👥 Людей с кошельком: <b>{t['people']}</b>\n"
                       f"🪙 Монет у всех: <b>{t['coins']}</b>\n"
                       f"🐾 Питомцев: <b>{t['pets']}</b>\n\n"
                       f"🧪 <b>Ты:</b> {w['coins']} 🪙, {w['level']} ур., питомец: {pet_line}\n\n"
                       "Цены, награды и питомцы правятся в коде: bot/economy/catalog.py",
               kb([[("🎁 Выдать монеты людям", "eca:give", "success")],
                   [("+1 000 мне", "eca:me:1000"), ("+10 000 мне", "eca:me:10000"), ("+100 000 мне", "eca:me:100000")],
                   [("🔄 Сбросить мой бонус", "eca:bonus"), ("😿 Питомец голодный", "eca:hungry")],
                   [("🗑 Убрать моего питомца", "eca:nopet"), ("0️⃣ Обнулить мои монеты", "eca:zero")],
                   [("👤 Открыть мой профиль", "pf:home", "primary")],
                   [("⬅️ Деньги", "sec:money"), BACK_MENU]]))


@router.callback_query(F.data == "eca:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await _menu(cb, cb.from_user.id)


@router.callback_query(F.data.startswith("eca:me:"))
async def cb_me(cb: CallbackQuery) -> None:
    balance = await store.add_coins(cb.from_user.id, int(cb.data[7:]), cb.from_user.full_name)
    await cb.answer(f"Готово, у тебя {balance} 🪙")
    await _menu(cb, cb.from_user.id)


@router.callback_query(F.data.in_({"eca:bonus", "eca:hungry", "eca:nopet", "eca:zero"}))
async def cb_tests(cb: CallbackQuery) -> None:
    uid, action = cb.from_user.id, cb.data[4:]
    await store.wallet(uid, cb.from_user.full_name)
    if action == "bonus":
        await store.update_wallet(uid, bonus_day="")
        note = "Бонус можно забрать снова (серия сохранилась)"
    elif action == "hungry":
        if not await store.pet(uid):
            return await cb.answer("сначала заведи питомца в профиле", show_alert=True)
        await store.update_pet(uid, satiety=5, fed_at=time.time(), warned=0)
        note = "Питомец голодный. Днём (10-22) в течение минуты бот напишет тебе в личку"
    elif action == "nopet":
        await store.delete_pet(uid)
        note = "Питомца нет, можно купить заново"
    else:
        await store.update_wallet(uid, coins=0)
        note = "Монеты обнулены"
    await cb.answer(note, show_alert=True)
    await _menu(cb, uid)


@router.callback_query(F.data == "eca:give")
async def cb_give(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiveCoins.who)
    await cb.answer()
    await show(cb, "🎁 <b>Выдать монеты</b>\n\nПришли, кому: <b>@username</b> или <b>ID</b>. Можно сразу многим через "
                   "запятую, пробел или с новой строки, например:\n<code>@kilka, @colos, 123456789</code>\n\n"
                   "Человек должен хоть раз писать в чате с ботом или в личку.",
               kb([[("Отмена", "eca:menu")]]))


@router.message(GiveCoins.who, F.text)
async def on_who(message: Message, state: FSMContext) -> None:
    found, missing = [], []
    for raw in message.text.replace(",", " ").replace(";", " ").split():
        person = await db.find_person(raw)
        (found.append(person) if person else missing.append(raw))
    if not found:
        return await message.answer("Никого не нашёл. Проверь @username или ID и пришли ещё раз.")
    await state.update_data(ids=[(p["user_id"], p["name"]) for p in found])
    await state.set_state(GiveCoins.amount)
    names = ", ".join(esc(p["name"] or str(p["user_id"])) for p in found)
    miss = f"\n⚠️ Не нашёл: {esc(', '.join(missing))}" if missing else ""
    await message.answer(f"Кому: {names}{miss}\n\nСколько монет каждому? Пришли число. "
                         "Минус, чтобы забрать, например <code>-500</code>.", parse_mode="HTML",
                         reply_markup=kb([[("Отмена", "eca:menu")]]))


@router.message(GiveCoins.amount, F.text)
async def on_amount(message: Message, state: FSMContext) -> None:
    raw = message.text.strip().replace(" ", "")
    if not raw.lstrip("-").isdigit() or not int(raw):
        return await message.answer("Пришли число, например 1000 или -500")
    amount = int(raw)
    ids = (await state.get_data())["ids"]
    await state.clear()
    lines = []
    for uid, name in ids:
        balance = await store.add_coins(uid, amount, name)
        lines.append(f"• {esc(name or str(uid))}: {'+' if amount > 0 else ''}{amount}, теперь {balance} 🪙")
    await message.answer("✅ Готово\n\n" + "\n".join(lines), parse_mode="HTML",
                         reply_markup=kb([[("💰 Экономика", "eca:menu")]]))
