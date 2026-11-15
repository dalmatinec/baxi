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


class BackupSet(StatesGroup):
    channel = State()
    file = State()


@router.callback_query(F.data == "cfg:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    creator = ("узнаю только по ID (" + ", ".join(str(i) for i in sorted(config.CREATOR_IDS)) + "), хвалю по-своему"
               if config.CREATOR_IDS else "выключен (CREATOR=0 в .env)")
    text = ("⚙️ <b>Настройки</b>\n\n"
            f"😎 Премиум-эмодзи бота: <b>{len(await db.emoji_list())}</b>\n"
            f"👑 Создатель: {creator}\n"
            f"🎁 Пробный период: <b>{config.TRIAL_DAYS} дн.</b> (TRIAL_DAYS в .env)\n"
            f"🤖 Лимит ИИ в сутки: <b>${config.DAILY_LIMIT_USD:.2f}</b> (DAILY_LIMIT_USD в .env)\n\n"
            "<i>Строки в .env меняются на сервере: nano /opt/linkhub/.env, потом systemctl restart linkhub</i>")
    await show(cb, text, kb([[("💾 Бэкап", "cfg:bk", "primary"), ("😎 Премиум-эмодзи", "cfg:emoji")],
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


# ---------- бэкап ----------

async def _backup_screen(target) -> None:
    import time as _t
    from bot.services import backup
    last = int(await db.kv_get("backup_last", "0") or 0)
    size = int(await db.kv_get("backup_size", "0") or 0)
    channel = await db.kv_get("backup_channel")
    local = sorted(backup.folder().glob("baxi-*.db.gz*")) if backup.folder().exists() else []
    when = "ещё не было" if not last else f"{int((_t.time() - last) // 3600)} ч назад, {size / 1024 / 1024:.1f} МБ"
    text = ("💾 <b>Бэкап</b>\n\n"
            f"Последний: <b>{when}</b>\n"
            f"Копий на сервере: <b>{len(local)}</b> (7 дней и 4 недели)\n"
            f"Закрытый канал: <b>{'подключён' if channel else 'не указан'}</b>\n"
            f"Шифрование: <b>{'включено' if backup.PASSWORD else 'выключено'}</b>\n"
            f"Время: каждый день в {backup.HOUR}:00\n\n"
            "Тебе в личку пишу, только если бэкап не получился.\n\n"
            "<b>Восстановить:</b> перешли сюда файл бэкапа из канала, я проверю его и предложу перезапуститься "
            "с этой копией. Текущая база сохранится рядом.")
    if not backup.PASSWORD:
        text += ("\n\n<i>Чтобы шифровать файлы, на сервере:</i>\n<code>echo \"BACKUP_PASSWORD=$(openssl rand -hex 16)\" "
                 ">> /opt/linkhub/.env && grep BACKUP_PASSWORD /opt/linkhub/.env</code>\n"
                 "<i>Сохрани пароль себе в Избранное и перезапусти бота. Без пароля файлы из канала не открыть.</i>")
    await show(target, text, kb([[("💾 Сделать сейчас", "cfg:bk:now", "success")],
                                 [("📢 Указать канал", "cfg:bk:ch"), ("♻️ Восстановить", "cfg:bk:rs")],
                                 [("⬅️ Настройки", "cfg:menu"), BACK_MENU]]))


@router.callback_query(F.data == "cfg:bk")
async def cb_backup(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _backup_screen(cb)


@router.callback_query(F.data == "cfg:bk:now")
async def cb_backup_now(cb: CallbackQuery, bot: Bot) -> None:
    from bot.services import backup
    await cb.answer("Делаю бэкап...")
    try:
        path = await backup.run(bot)
    except Exception as exc:
        return await cb.message.answer(f"⚠️ Не получилось: {esc(str(exc)[:300])}", parse_mode="HTML")
    channel = await db.kv_get("backup_channel")
    await cb.message.answer(f"✅ Готово: {path.name}" + (", копия в канале" if channel else ", канал не указан"))
    await _backup_screen(cb.message)


@router.callback_query(F.data == "cfg:bk:ch")
async def cb_backup_channel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackupSet.channel)
    await show(cb, "📢 <b>Канал для бэкапов</b>\n\n1. Создай закрытый канал, например «Бакси бэкапы».\n"
                   "2. Добавь туда бота админом с правом публиковать и удалять сообщения.\n"
                   "3. Перешли сюда любое сообщение из этого канала.\n\nИли пришли id канала вида -100...",
               kb([[("Отмена", "cfg:bk")]]))


@router.message(BackupSet.channel)
async def on_backup_channel(message: Message, bot: Bot, state: FSMContext) -> None:
    origin = getattr(message, "forward_origin", None)
    chat = getattr(origin, "chat", None) or getattr(message, "forward_from_chat", None)
    channel_id = chat.id if chat else None
    if channel_id is None and message.text and message.text.strip().lstrip("-").isdigit():
        channel_id = int(message.text.strip())
    if channel_id is None:
        return await message.answer("Перешли сообщение именно из канала или пришли его id.")
    try:
        test = await bot.send_message(channel_id, "✅ Сюда будут приходить бэкапы Бакси, раз в сутки, без звука.",
                                      disable_notification=True)
    except Exception as exc:
        return await message.answer(f"Не могу писать в этот канал: {esc(str(exc)[:200])}\n"
                                    "Проверь, что бот там админ с правом публиковать.", parse_mode="HTML")
    await db.kv_set("backup_channel", str(channel_id))
    await state.clear()
    await message.answer(f"✅ Канал подключён (сообщение {test.message_id}). Сделать первый бэкап сейчас?",
                         reply_markup=kb([[("💾 Сделать сейчас", "cfg:bk:now", "success")], [("⬅️ Бэкап", "cfg:bk")]]))


@router.callback_query(F.data == "cfg:bk:rs")
async def cb_backup_restore(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BackupSet.file)
    await show(cb, "♻️ <b>Восстановление</b>\n\nПерешли сюда файл бэкапа из канала (baxi-....db.gz или .enc). "
                   "Я проверю его, и ты решишь, перезапускаться с ним или нет.", kb([[("Отмена", "cfg:bk")]]))


@router.message(BackupSet.file, F.document)
async def on_backup_file(message: Message, bot: Bot, state: FSMContext) -> None:
    from bot.services import backup
    doc = message.document
    if not (doc.file_name or "").startswith("baxi-"):
        return await message.answer("Это не похоже на файл бэкапа Бакси. Нужен файл baxi-....db.gz или .enc.")
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        return await message.answer("Файл больше 20 МБ, через бота его не скачать. Восстанови на сервере: "
                                    "bash /opt/linkhub/deploy/restore.sh путь_к_файлу")
    backup.folder().mkdir(parents=True, exist_ok=True)
    dest = backup.folder() / f"upload-{doc.file_name}"
    await bot.download(doc, destination=dest)
    try:
        summary = await backup.prepare_restore(dest)
    except Exception as exc:
        return await message.answer(f"⚠️ Не подходит: {esc(str(exc)[:300])}", parse_mode="HTML")
    finally:
        dest.unlink(missing_ok=True)
    await state.clear()
    await message.answer(f"✅ Копия проверена, {summary}.\n\nПерезапустить бота с этой копией? Текущая база "
                         "сохранится рядом как bot.db.before-restore.",
                         reply_markup=kb([[("♻️ Да, перезапустить", "cfg:bk:go", "danger")],
                                          [("Отмена", "cfg:bk:no")]]))


@router.callback_query(F.data.in_({"cfg:bk:go", "cfg:bk:no"}))
async def cb_backup_go(cb: CallbackQuery) -> None:
    import asyncio
    import os
    if cb.data == "cfg:bk:no":
        (config.DATA_DIR / "restore.db").unlink(missing_ok=True)
        await cb.answer("Отменено")
        return await _backup_screen(cb)
    await cb.message.answer("♻️ Перезапускаюсь с копией, через 10 секунд напиши /admin.")
    await cb.answer()
    await asyncio.sleep(1)
    os._exit(3)  # systemd поднимет бота заново, при старте база подменится
