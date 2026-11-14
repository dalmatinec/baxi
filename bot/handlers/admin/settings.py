"""Админка → Настройки: премиум-эмодзи бота, меню команд, создатель."""

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config, db
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.services import emoji
from bot.textutil import esc

router = Router(name="admin-settings")


class EmojiAdd(StatesGroup):
    collecting = State()


@router.callback_query(F.data == "cfg:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    creator = (f"{esc(config.CREATOR_NAME)}, отмечаю его как создателя и хвалю по-своему"
               if config.CREATOR_NAME else "выключен (CREATOR_NAME в .env)")
    text = ("⚙️ <b>Настройки</b>\n\n"
            f"😎 Премиум-эмодзи бота: <b>{len(await db.emoji_list())}</b>\n"
            f"👑 Создатель: {creator}\n"
            f"🎁 Пробный период: <b>{config.TRIAL_DAYS} дн.</b> (TRIAL_DAYS в .env)\n"
            f"🤖 Лимит ИИ в сутки: <b>${config.DAILY_LIMIT_USD:.2f}</b> (DAILY_LIMIT_USD в .env)\n\n"
            "<i>Строки в .env меняются на сервере: nano /opt/linkhub/.env, потом systemctl restart linkhub</i>")
    await show(cb, text, kb([[("😎 Премиум-эмодзи", "cfg:emoji", "primary")],
                             [("🔄 Обновить меню команд", "cfg:cmds")], [BACK_MENU]]))


async def _emoji_screen(target) -> None:
    rows = await db.emoji_list()
    sample = "".join(f'<tg-emoji emoji-id="{r["emoji_id"]}">{r["alt"]}</tg-emoji>' for r in rows[:50])
    text = ("😎 <b>Премиум-эмодзи бота</b>\n\n"
            "Бот ставит их в свои сообщения вместо обычных: в ответах, играх, итогах. Пришли сюда сообщение "
            "с премиум-эмодзи (можно сразу много), я запомню. Нейросеть тоже будет ими пользоваться.\n\n"
            "<i>Анимированные премиум-эмодзи видны людям, если у владельца бота есть Telegram Premium. "
            "Иначе показывается обычный эмодзи, ничего не ломается.</i>\n\n"
            + (f"Сейчас ({len(rows)}): {sample}" if rows else "Пока пусто."))
    await show(target, text, kb([[("🗑 Очистить все", "cfg:emoji:clear", "danger")] if rows else [],
                                 [("⬅️ Настройки", "cfg:menu"), BACK_MENU]]))


@router.callback_query(F.data == "cfg:emoji")
async def cb_emoji(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EmojiAdd.collecting)
    await _emoji_screen(cb)


@router.callback_query(F.data == "cfg:emoji:clear")
async def cb_emoji_clear(cb: CallbackQuery) -> None:
    await db.emoji_clear()
    await emoji.load()
    await _emoji_screen(cb)


@router.message(EmojiAdd.collecting)
async def on_emoji(message: Message) -> None:
    found = emoji.extract(message)
    if not found:
        return await message.answer("Тут нет премиум-эмодзи. Пришли сообщение именно с ними или нажми Настройки.")
    for emoji_id, alt in found:
        await db.emoji_add(emoji_id, alt)
    await emoji.load()
    await message.answer(f"✅ Запомнил {len(found)}. Можно прислать ещё.")
    await _emoji_screen(message)


@router.callback_query(F.data == "cfg:cmds")
async def cb_cmds(cb: CallbackQuery, bot: Bot) -> None:
    from bot.services.commands_menu import set_commands
    await set_commands(bot)
    await cb.answer("🔄 Меню команд обновлено", show_alert=True)
