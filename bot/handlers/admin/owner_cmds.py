"""Команды только для владельца в личке (их видишь только ты в меню по кнопке /):
  /admin    админка
  /health   состояние сервера: память, диск, пульс, бэкап
  /preview  итоги дня картинками для любого чата, только тебе
  /backup   бэкап базы прямо сейчас (в канал бэкапов, если он задан)
  /give     выдать монеты людям (можно сразу многим)
  /chats    список чатов
  /maint    режим «меня обновляют»: /maint (на 2 часа), /maint 30 (на 30 минут), /maint off
Работают только в личке и только для OWNER_IDS (фильтр в admin/__init__.py)."""

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import db
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.textutil import short

router = Router(name="admin-owner-cmds")


@router.message(Command("health"))
async def cmd_health(message: Message, state: FSMContext) -> None:
    from bot.handlers.admin.settings import health_text
    await state.clear()
    await show(message, await health_text(), kb([[("🔄 Обновить", "cfg:hl")], [BACK_MENU]]))


@router.message(Command("preview"))
async def cmd_preview(message: Message, state: FSMContext) -> None:
    await state.clear()
    chats = [c for c in await db.list_chats() if c["approved"]]
    if not chats:
        return await message.answer("Чатов пока нет.")
    rows = [[(f"👁 {short(c['title'] or str(c['chat_id']), 40)}", f"ch:rp:{c['chat_id']}")] for c in chats[:30]]
    await show(message, "👁 <b>Итоги дня картинками</b>\n\nВыбери чат: соберу итоги за сегодня и пришлю только тебе, "
                        "в чат ничего не уйдёт.", kb(rows + [[BACK_MENU]]))


@router.message(Command("backup"))
async def cmd_backup(message: Message, bot: Bot, state: FSMContext) -> None:
    from bot.services import backup
    await state.clear()
    wait = await message.answer("💾 Делаю бэкап…")
    try:
        path = await backup.run(bot)
        await wait.edit_text(f"✅ Бэкап готов: {path.name}, {path.stat().st_size // 1024} КБ")
    except Exception as exc:
        await wait.edit_text(f"⚠️ Бэкап не получился: {exc}")


@router.message(Command("give"))
async def cmd_give(message: Message, state: FSMContext) -> None:
    from bot.handlers.admin.economy import GiveCoins
    await state.set_state(GiveCoins.who)
    await message.answer("🎁 Кому выдать монеты? Пришли @username или ID, можно сразу многим через запятую.\n"
                         "Отмена: /cancel")


@router.message(Command("chats"))
async def cmd_chats(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message, "💬 Чаты", kb([[("💬 Открыть список чатов", "ch:list")]]))


@router.message(Command("maint"))
async def cmd_maint(message: Message, state: FSMContext) -> None:
    import time
    from datetime import datetime

    from bot import config
    from bot.services import maint
    await state.clear()
    arg = ((message.text or "").split(maxsplit=1)[1:] or [""])[0].strip().lower()
    if arg in ("off", "выкл", "0", "стоп", "нет"):
        await maint.turn_off()
        return await message.answer("✅ Режим обновления выключен, бот снова говорит как обычно.")
    if not arg and maint.is_on():
        left = int((maint.until() - time.time()) // 60) + 1
        return await message.answer(f"🔧 Режим обновления включён ещё {left} мин.\n"
                                    "Выключить: /maint off. Продлить: /maint 60")
    minutes = int(arg) if arg.isdigit() and 1 <= int(arg) <= 1440 else maint.DEFAULT_MIN
    until = await maint.turn_on(minutes)
    await message.answer(f"🔧 Режим обновления включён до {datetime.fromtimestamp(until, config.TZ):%H:%M}.\n\n"
                         "Нейросеть на паузе, сам в разговоры не лезет, на обращения отвечает шуткой вроде "
                         f"<i>{maint.PHRASES[0]}</i>\nИгры и команды работают. Выключить: /maint off",
                         parse_mode="HTML")
