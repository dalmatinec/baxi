"""Команды только для владельца в личке (их видишь только ты в меню по кнопке /):
  /admin    админка
  /health   состояние сервера: память, диск, пульс, бэкап
  /preview  итоги дня картинками для любого чата, только тебе
  /backup   бэкап базы прямо сейчас (в канал бэкапов, если он задан)
  /give     выдать монеты людям (можно сразу многим)
  /chats    список чатов
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
