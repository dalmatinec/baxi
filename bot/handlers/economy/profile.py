"""Личка бота: свой профиль у каждого человека. Монеты, уровень, бонус, питомец, магазин, пополнение
звёздами или криптой, как заработать, о боте, свой бот и сайт. Кнопки: pf:*, оплата криптой: pf:cx:*.

Открывается: кнопкой «👤 Профиль и магазин» в меню, /profile или /shop в личке, ссылкой из чата (start=profile)."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, User

from bot import config, db
from bot.economy import catalog, service, store
from bot.handlers.economy.common import EARN_TEXT, kb, name_of, pet_title, profile_lines, send_pet
from bot.services import adorders, stars, texts
from bot.textutil import esc, mention

log = logging.getLogger(__name__)
router = Router(name="economy_profile")
router.message.filter(F.chat.type == "private")


class PetName(StatesGroup):
    name = State()


BACK = ("⬅️ Профиль", "pf:home")


def PET_EXTRA() -> list:  # noqa: N802  кнопки под карточкой питомца в личке
    return kb([[("✏️ Кличка", "pf:rn"), ("🐾 Взять круче", "pf:pets")], [BACK]]).inline_keyboard


# ---------- экраны ----------

async def profile_screen(user: User) -> tuple[str, object]:
    w = await store.wallet(user.id, name_of(user))
    perks = await db.get_perks(user.id)
    nick = "✨ Свой ник: есть навсегда" if perks and perks["look_forever"] else "✨ Свой ник: нет, можно купить"
    text = "\n".join([f"👤 <b>Профиль</b> {mention(user.id, name_of(user))}", "", *await profile_lines(user), nick, "",
                      "<i>Монеты и питомец общие во всех чатах.</i>"])
    rows = [[("🎁 Забрать бонус", "pf:bonus", "success")] if service.bonus_ready(w) else [],
            [("🐾 Мой питомец", "pf:pet", "primary"), ("🛒 Магазин", "pf:shop", "primary")],
            [("💳 Пополнить", "pf:top", "success"), ("💡 Как заработать", "pf:earn")],
            [("🤖 О боте и команды", "pf:about"), ("💼 Свой бот", "sc:wl")] if config.IS_MAIN else
            [("🤖 О боте и команды", "pf:about")],
            [("📜 Правила", "sc:terms")],
            [("🌐 Сайт", config.SITE_URL)] if config.SITE_URL else [],
            [("🧪 Тесты (видишь только ты)", "eca:menu", "danger")] if user.id in config.OWNER_IDS else [],
            [("⬅️ Меню", "sc:start")]]
    return text, kb(rows)


async def shop_screen(user: User) -> tuple[str, object]:
    w = await store.wallet(user.id, name_of(user))
    perks = await db.get_perks(user.id)
    has_nick = bool(perks and perks["look_forever"])
    text = ("🛒 <b>Магазин</b>\n"
            f"Баланс: <b>{w['coins']} 🪙</b>\n\n"
            f"✨ <b>Свой ник навсегда</b> · {catalog.NICK_PRICE} 🪙\n"
            "<i>Премиум-эмодзи и жирный ник у имени везде, где бот тебя упоминает: топы, итоги, игры. "
            "Любой шрифт, какой пришлёшь.</i>\n\n"
            f"🐾 <b>Питомцы</b> · {len(catalog.PETS)} видов от {catalog.PETS[catalog.PET_ORDER[0]]['price']} 🪙\n"
            "<i>От улитки до дракона. У каждого своя еда. Кто сильнее, тот выше в топе питомцев чата.</i>\n\n"
            "💳 <b>Пополнить монеты</b> звёздами или криптой")
    rows = [[("✏️ Настроить мой ник", "st:vip", "success")] if has_nick else
            [(f"✨ Ник навсегда · {catalog.NICK_PRICE} 🪙", "pf:nick", "success")],
            [("🐾 Питомцы", "pf:pets", "primary"), ("💳 Пополнить", "pf:top", "success")],
            [BACK]]
    return text, kb(rows)


def pets_screen() -> tuple[str, object]:
    lines = ["🐾 <b>Питомцы</b>", "<i>Цена · сила · еда. Покупка заменяет текущего питомца на более крутого.</i>", ""]
    buttons = []
    for key in catalog.PET_ORDER:
        p = catalog.PETS[key]
        lines.append(f"{p['emoji']} <b>{p['name']}</b> · {p['price']} 🪙 · 💪 {p['power']} · "
                     f"{p['food'][1]} {p['food'][0]} {p['food'][2]} 🪙")
        buttons.append((f"{p['emoji']} {p['name']} · {p['price']}", f"pf:pb:{key}"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return "\n".join(lines), kb(rows + [[("⬅️ Магазин", "pf:shop")]])


async def topup_screen() -> tuple[str, object]:
    items = await stars.items_map()
    star_rows = [(f"⭐ {coins} монет · {items[key]['stars']} ⭐", f"pf:st:{key}", "success")
                 for key, (coins, *_) in catalog.COIN_PACKS.items() if key in items]
    rows = [star_rows[i:i + 2] for i in range(0, len(star_rows), 2)]
    text = ("💳 <b>Пополнить монеты</b>\n\n"
            "⭐ <b>Звёздами Telegram</b>: жми на сумму, монеты придут сразу после оплаты.")
    if adorders.can_pay():
        rows.append([("💎 Криптой (USDT)", "pf:cr", "primary")])
        prices = ", ".join(f"{c} за {usd} USDT" for c, _, usd in catalog.COIN_PACKS.values())
        text += f"\n💎 <b>Криптой</b>: USDT в сети TON или TRC20. {prices}."
    text += ("\n\n⚠️ Монеты игровые: их нельзя вывести или обменять на деньги, возврата после начисления нет. "
             "Оплачивая, ты соглашаешься с правилами.")
    return text, kb(rows + [[("📜 Правила", "sc:terms"), BACK]])


async def about_screen(bot: Bot) -> tuple[str, object]:
    me = await bot.me()
    text = (f"🤖 <b>{esc(config.DEFAULT_NAME or me.first_name or 'Бот')}</b>\n\n"
            "Живой участник твоего чата: болтает в своём характере, помнит людей, подводит итоги дня, "
            "устраивает викторины, зовёт всех в игру, а ещё монеты, уровни, питомцы и кости.\n\n"
            "<b>Главное в чате:</b> /games все игры кнопками, кошелёк, бонус, питомец, топ питомцев, богачи, "
            "кости 100 ответом, передать 100 ответом.\n\n"
            "Все команды и описание на сайте 👇")
    rows = [[("➕ Добавить в свой чат", f"https://t.me/{me.username}?startgroup=true", "success")],
            [("📖 Все команды на сайте", f"{config.SITE_URL}/baxi#commands")] if config.SITE_URL else [],
            [BACK]]
    return text, kb(rows)


async def show(target: Message | CallbackQuery, text: str, markup) -> None:
    """Показать экран: при нажатии кнопки заменяем текст, под картинкой шлём новое сообщение."""
    if isinstance(target, CallbackQuery):
        await target.answer()
        if target.message.text:
            try:
                return await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
        target = target.message
    await target.answer(text, parse_mode="HTML", reply_markup=markup)


async def open_profile(message: Message) -> None:
    await show(message, *await profile_screen(message.from_user))


async def open_shop(message: Message) -> None:
    await show(message, *await shop_screen(message.from_user))


# кнопка «👤 Профиль и магазин» стоит в главном меню (bot/screens.py, действие pf:home)


# ---------- команды ----------

@router.message(Command("profile", "me", "wallet"))
async def cmd_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    await open_profile(message)


# ---------- кнопки ----------

@router.callback_query(F.data.startswith("pf:"))
async def on_button(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    if cb.message.chat.type != "private":
        return await cb.answer()
    parts = cb.data.split(":")
    action, user = parts[1], cb.from_user
    await state.clear()
    try:
        await _button(cb, bot, state, user, action, parts)
    except Exception:
        log.exception("Профиль: кнопка %s", cb.data)
        await cb.answer("что-то пошло не так, попробуй ещё раз", show_alert=True)


async def _button(cb: CallbackQuery, bot: Bot, state: FSMContext, user: User, action: str, parts: list[str]) -> None:
    if action == "home":
        await show(cb, *await profile_screen(user))
    elif action == "bonus":
        got = await service.claim_bonus(user.id, name_of(user))
        if not got:
            return await cb.answer("бонус уже забран сегодня, приходи завтра", show_alert=True)
        await cb.answer(f"🎁 +{got[0]} 🪙, серия {got[1]} дн.", show_alert=True)
        await show(cb, *await profile_screen(user))
    elif action == "shop":
        await show(cb, *await shop_screen(user))
    elif action == "pets":
        await show(cb, *pets_screen())
    elif action == "pet":
        await cb.answer()
        if not await send_pet(bot, user.id, user, config.DEFAULT_NAME or "", extra=PET_EXTRA()):
            await show(cb.message, "🐾 У тебя пока нет питомца. Выбирай: от улитки до дракона, у каждого своя еда.",
                       kb([[("🐾 Выбрать питомца", "pf:pets", "success")], [BACK]]))
    elif action == "pb":
        await _confirm_pet(cb, user, parts[2])
    elif action == "pk":
        why = await service.buy_pet(user.id, name_of(user), parts[2])
        if why:
            return await cb.answer(why, show_alert=True)
        info = catalog.PETS[parts[2]]
        await cb.answer(f"{info['emoji']} {info['name']} теперь твой!")
        await state.set_state(PetName.name)
        text = await texts.render("eco_new_pet", кто=mention(user.id, name_of(user)), вид=info["name"],
                                  эмодзи=info["emoji"])
        await show(cb, text, kb([[("Пропустить", "pf:pet")]]))
    elif action == "rn":
        if not await store.pet(user.id):
            return await cb.answer("у тебя ещё нет питомца", show_alert=True)
        await cb.answer()
        await state.set_state(PetName.name)
        await cb.message.answer("✏️ Напиши новую кличку (до 20 символов):", reply_markup=kb([[("Отмена", "pf:pet")]]))
    elif action == "top":
        await show(cb, *await topup_screen())
    elif action == "st":
        item = (await stars.items_map()).get(parts[2])
        if not item:
            return await cb.answer("недоступно", show_alert=True)
        await cb.answer()
        await bot.send_invoice(user.id, title=item["title"][:32], description=stars.item_text(parts[2])[:255],
                               payload=parts[2], currency="XTR",
                               prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])])
    elif action == "cr":
        rows = [[(f"🪙 {coins} монет · {usd} USDT", f"pf:cx:{key}", "success")]
                for key, (coins, _, usd) in catalog.COIN_PACKS.items()]
        await show(cb, "💎 <b>Пополнить криптой</b>\n\nВыбери сумму. Потом пришлю адрес и точную сумму в USDT, "
                       "монеты придут сами, как только оплата дойдёт.", kb(rows + [[("⬅️ Назад", "pf:top")]]))
    elif action == "cx":
        pack = catalog.COIN_PACKS.get(parts[2])
        if not pack or not adorders.can_pay():
            return await cb.answer("недоступно", show_alert=True)
        name = name_of(user) + (f" @{user.username}" if user.username else "")
        oid = await db.create_order(user.id, name, "coins", f"🪙 {pack[0]} монет", pack[2], pack[0], "", "", "", [],
                                    "awaiting")
        await cb.answer()
        await adorders.start_payment(bot, oid)
    elif action == "earn":
        await show(cb, EARN_TEXT.replace("{bot}", esc(config.DEFAULT_NAME or "бот")),
                   kb([[("🛒 Магазин", "pf:shop", "primary")], [BACK]]))
    elif action == "about":
        await show(cb, *await about_screen(bot))
    elif action == "nick":
        w = await store.wallet(user.id, name_of(user))
        if w["coins"] < catalog.NICK_PRICE:
            return await cb.answer(f"нужно {catalog.NICK_PRICE} 🪙, у тебя {w['coins']}", show_alert=True)
        await show(cb, f"✨ Купить свой ник навсегда за <b>{catalog.NICK_PRICE} 🪙</b>?\nПосле покупки сразу настроишь "
                       "премиум-эмодзи и ник.", kb([[("✅ Купить", "pf:nk", "success"), ("Отмена", "pf:shop")]]))
    elif action == "nk":
        why = await service.buy_look(user.id)
        if why:
            return await cb.answer(why, show_alert=True)
        await stars.refresh_looks()
        await cb.answer("✨ Ник твой навсегда!", show_alert=True)
        from bot.handlers.stars import look_screen
        await look_screen(cb, user)
    else:
        await cb.answer()


async def _confirm_pet(cb: CallbackQuery, user: User, species: str) -> None:
    info = catalog.PETS.get(species)
    current = await store.pet(user.id)
    why = service.can_buy(current, species)
    if why:
        return await cb.answer(why, show_alert=True)
    coins = (await store.wallet(user.id, name_of(user)))["coins"]
    if coins < info["price"]:
        return await cb.answer(f"нужно {info['price']} 🪙, у тебя {coins}. Как заработать: в профиле", show_alert=True)
    swap = f"\n\nТвой {pet_title(current)} уйдёт, новый начнёт с 1 уровня." if current else ""
    food = info["food"]
    await show(cb, f"{info['emoji']} <b>{info['name']}</b> за <b>{info['price']} 🪙</b>?\n"
                   f"💪 Сила {info['power']} · ест {food[0]} {food[1]} по {food[2]} 🪙{swap}",
               kb([[("✅ Купить", f"pf:pk:{species}", "success"), ("Отмена", "pf:pets")]]))


@router.message(PetName.name, F.text)
async def on_pet_name(message: Message, bot: Bot, state: FSMContext) -> None:
    why = await service.rename_pet(message.from_user.id, message.text)
    if why:
        return await message.answer(f"{why}. Попробуй ещё раз.")
    await state.clear()
    await send_pet(bot, message.chat.id, message.from_user, config.DEFAULT_NAME or "", extra=PET_EXTRA())
