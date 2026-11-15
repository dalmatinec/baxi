"""Админка → Настройки: премиум-эмодзи бота, меню команд, создатель."""

import os

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


class PlanPersona(StatesGroup):
    value = State()


class TextEdit(StatesGroup):
    value = State()


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
            f"🤖 Лимит ИИ в сутки: <b>${config.DAILY_LIMIT_USD:.2f}</b> (меняется в 🤖 ИИ и расход)\n\n"
            "<i>Строки в .env меняются на сервере: nano /opt/linkhub/.env, потом systemctl restart linkhub</i>")
    await show(cb, text, kb([[("💾 Бэкап", "cfg:bk", "primary"), ("😎 Премиум-эмодзи", "cfg:emoji")],
                             [("🎁 Пробный и бесплатный", "cfg:pl"), ("✏️ Тексты бота", "cfg:tx")],
                             [("🩺 Состояние сервера", "cfg:hl", "success"), ("🔄 Меню команд", "cfg:cmds")],
                             [BACK_MENU]]))


# ---------- состояние сервера ----------

STARTED = __import__("time").time()


def _mb(n: float) -> str:
    return f"{n / 1024 / 1024:,.0f} МБ".replace(",", " ")


def _meminfo() -> dict:
    out = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    return out


def _rss() -> int:
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


@router.callback_query(F.data == "cfg:hl")
async def cb_health(cb: CallbackQuery) -> None:
    """Сколько ест бот, сколько свободно памяти и диска, жив ли пульс, когда был бэкап."""
    import shutil
    import time
    now = time.time()
    mem = _meminfo()
    disk = shutil.disk_usage(config.DATA_DIR)
    db_size = sum(p.stat().st_size for p in config.DATA_DIR.glob("bot.db*") if p.is_file())
    backups = sum(p.stat().st_size for p in (config.DATA_DIR / "backups").glob("*") if p.is_file()) \
        if (config.DATA_DIR / "backups").exists() else 0
    beat_file = config.DATA_DIR / "heartbeat"
    beat = now - beat_file.stat().st_mtime if beat_file.exists() else None
    last_backup = int(await db.kv_get("backup_last") or 0)
    up = int(now - STARTED)
    rss, avail, total = _rss(), mem.get("MemAvailable", 0), mem.get("MemTotal", 0)
    swap_used = mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)
    warn = []
    if avail and avail < 200 * 1024 * 1024:
        warn.append("мало свободной памяти")
    if disk.free < 1024 ** 3:
        warn.append("меньше 1 ГБ на диске")
    if rss > 250 * 1024 * 1024:
        warn.append("бот ест много памяти, скоро systemd его перезапустит")
    if beat is None or beat > 300:
        warn.append("пульс давно не обновлялся")
    status = "🟢 Всё в порядке" if not warn else "🟠 Внимание: " + ", ".join(warn)
    text = (f"🩺 <b>Состояние сервера</b>\n\n{status}\n\n"
            f"🤖 Бот ест: <b>{_mb(rss)}</b> из 300 МБ лимита\n"
            f"🧠 Память сервера: свободно <b>{_mb(avail)}</b> из {_mb(total)}"
            + (f", в подкачке {_mb(swap_used)}" if swap_used > 0 else "") + "\n"
            f"💽 Диск: свободно <b>{disk.free / 1024 ** 3:.1f} ГБ</b> из {disk.total / 1024 ** 3:.0f} ГБ\n"
            f"🗄 База: {_mb(db_size)}, бэкапы: {_mb(backups)}\n"
            f"⏱ Работает без перезапуска: {up // 86400} дн. {up % 86400 // 3600} ч. {up % 3600 // 60} мин.\n"
            f"💓 Пульс: {'нет' if beat is None else f'{int(beat)} с назад'}\n"
            f"💾 Последний бэкап: {'не было' if not last_backup else f'{int((now - last_backup) / 3600)} ч. назад'}\n"
            f"💬 Чатов: {len(await db.list_chats())}\n\n"
            "<b>Защита:</b> автозапуск после перезагрузки, перезапуск при падении, лимит памяти 300 МБ, "
            "сторож раз в 5 минут (перезапустит зависшего бота и напишет тебе, если мало места), "
            "логи не больше 300 МБ, ежедневный бэкап. Ставится командой <code>bash /opt/linkhub/deploy/harden.sh</code>")
    await cb.answer()
    await show(cb, text, kb([[("🔄 Обновить", "cfg:hl")], [("⬅️ Настройки", "cfg:menu"), BACK_MENU]]))


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
    channel = os.getenv("BACKUP_CHANNEL", "").strip() or await db.kv_get("backup_channel")
    local = sorted(backup.folder().glob("baxi-*.db.gz*")) if backup.folder().exists() else []
    when = "ещё не было" if not last else f"{int((_t.time() - last) // 3600)} ч назад, {size / 1024 / 1024:.1f} МБ"
    text = ("💾 <b>Бэкап</b>\n\n"
            f"Последний: <b>{when}</b>\n"
            f"Копий на сервере: <b>{len(local)}</b> (7 дней и 4 недели)\n"
            f"Закрытый канал: <b>{'подключён' if channel else 'не указан'}</b>\n"
            f"Время: каждый день в {backup.HOUR}:00\n\n"
            "Тебе в личку пишу, только если бэкап не получился.\n\n"
            "<b>Восстановить:</b> перешли сюда файл бэкапа из канала, я проверю его и предложу перезапуститься "
            "с этой копией. Текущая база сохранится рядом.")
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
    await show(cb, "♻️ <b>Восстановление</b>\n\nПерешли сюда файл бэкапа из канала (baxi-....db.gz). "
                   "Я проверю его, и ты решишь, перезапускаться с ним или нет.", kb([[("Отмена", "cfg:bk")]]))


@router.message(BackupSet.file, F.document)
async def on_backup_file(message: Message, bot: Bot, state: FSMContext) -> None:
    from bot.services import backup
    doc = message.document
    if not (doc.file_name or "").startswith("baxi-"):
        return await message.answer("Это не похоже на файл бэкапа Бакси. Нужен файл baxi-....db.gz.")
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


# ---------- тексты бота в чатах ----------

def _texts() -> dict:
    """ключ → (название, текст по умолчанию, подсказка с подстановками моноширинным)."""
    from bot.services import texts
    return {key: (title, default, ", ".join(f"<code>{{{k}}}</code> {v[0]}" for k, v in subs.items()))
            for key, (_, title, default, subs) in texts.TEXTS.items()}


GROUP_ICONS = {"Репутация": "💜", "Монеты": "🪙", "Ранги": "🏅", "Кости": "🎲", "Питомцы": "🐾"}


@router.callback_query(F.data == "cfg:tx")
async def cb_texts(cb: CallbackQuery, state: FSMContext) -> None:
    """Тексты по разделам: сколько в разделе и сколько уже своих."""
    from bot.services import texts
    await state.clear()
    rows = []
    for n, group in enumerate(texts.groups()):
        keys = [k for k, v in texts.TEXTS.items() if v[0] == group]
        custom = len([k for k in keys if await db.kv_get(k)])
        mark = f" · ✏️ {custom} своих" if custom else ""
        rows.append([(f"{GROUP_ICONS.get(group, '📝')} {group} · {len(keys)}{mark}", f"cfg:txg:{n}")])
    await show(cb, "✏️ <b>Тексты бота в чатах</b>\n\nСообщения, которые бот пишет сам: репутация, монеты, кости, "
                   "питомцы. Выбери раздел, внутри можно посмотреть, как всё выглядит, и поменять любой текст.\n\n"
                   "Можно с премиум-эмодзи, жирным, курсивом: как пришлёшь, так и будет во всех чатах. "
                   "Обычные эмодзи бот сам меняет на премиум из эмодзи-пака (Настройки → Эмодзи).",
               kb(rows + [[("⬅️ Настройки", "cfg:menu"), BACK_MENU]]))


async def _group_screen(cb: CallbackQuery, n: int) -> None:
    from bot.services import texts
    group = texts.groups()[n]
    rows = []
    for key, (g, title, _, _) in texts.TEXTS.items():
        if g == group:
            rows.append([(("✏️ " if await db.kv_get(key) else "") + title, f"cfg:tx:{key}")])
    await show(cb, f"{GROUP_ICONS.get(group, '📝')} <b>{group}</b>\n\n✏️ значит текст уже свой. "
                   "Нажми на текст, чтобы посмотреть и поменять.",
               kb(rows + [[("👁 Показать все, как в чате", f"cfg:txp:{n}", "primary")], [("⬅️ Разделы", "cfg:tx")]]))


@router.callback_query(F.data.startswith("cfg:txg:"))
async def cb_text_group(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    await _group_screen(cb, int(cb.data[8:]))


@router.callback_query(F.data.startswith("cfg:txp:"))
async def cb_text_preview(cb: CallbackQuery) -> None:
    """Все тексты раздела с примерами имён и чисел, как их увидят в чате."""
    from bot.services import texts
    group = texts.groups()[int(cb.data[8:])]
    parts = [f"👁 <b>{group}: как это выглядит в чате</b>"]
    for key, (g, title, default, _) in texts.TEXTS.items():
        if g == group:
            parts.append(f"<b>{title}</b>\n{texts.sample(key, await db.kv_get(key) or default)}")
    await cb.answer()
    await cb.message.answer("\n\n➖➖➖\n\n".join(parts), parse_mode="HTML",
                            reply_markup=kb([[("⬅️ К разделу", cb.data.replace("txp", "txg"))]]))


@router.callback_query(F.data.startswith("cfg:tx:"))
async def cb_text_item(cb: CallbackQuery, state: FSMContext) -> None:
    from bot.services import texts
    key = cb.data[7:]
    reset = key.startswith("reset:")
    key = key[6:] if reset else key
    title, default, hint = _texts()[key]
    if reset:
        await db.kv_set(key, "")
        await cb.answer("Вернул стандартный")
    own = await db.kv_get(key)
    current = own or default
    group_n = texts.groups().index(texts.TEXTS[key][0])
    await state.set_state(TextEdit.value)
    await state.update_data(key=key)
    await show(cb, f"✏️ <b>{title}</b> ({'свой' if own else 'стандартный'})\n\n"
                   f"<b>Так увидят в чате:</b>\n{texts.sample(key, current)}\n\n"
                   f"<b>Подстановки</b> (нажми, чтобы скопировать): {hint}\n\n"
                   "Пришли новый текст сообщением. Подстановки бот сам заменит на имена и числа.",
               kb([[("↩️ Вернуть стандартный", f"cfg:tx:reset:{key}")] if own else [],
                   [("⬅️ К разделу", f"cfg:txg:{group_n}")]]))


@router.message(TextEdit.value, F.text)
async def on_text_value(message: Message, state: FSMContext) -> None:
    key = (await state.get_data())["key"]
    await db.kv_set(key, message.html_text[:1500])
    await state.clear()
    title = _texts()[key][0]
    from bot.services import texts
    await message.answer(f"✅ {title}: сохранил. Так это будет выглядеть:\n\n"
                         + texts.sample(key, message.html_text[:1500]),
                         parse_mode="HTML", reply_markup=kb([[("⬅️ К разделу", f"cfg:txg:{texts.groups().index(texts.TEXTS[key][0])}")]]))


# ---------- пробный и бесплатный тарифы ----------

PLAN_STEPS = {"max_trials": [5, 10, 20, 50], "min_members": [0, 5, 10, 20, 50], "free_ai": [0, 10, 20, 50],
              "nudges": [0, 1, 2]}


async def _plans_screen(target) -> None:
    import time as _t
    from bot.services import plans
    chats = await db.list_chats()
    trials = sum(1 for c in chats if c["trial"] and c["rent_until"] > _t.time())
    free = sum(1 for c in chats if c["free"])
    st = plans.SETTINGS
    text = ("🎁 <b>Пробный и бесплатный</b>\n\n"
            f"Сейчас: на пробном <b>{trials}</b>, на бесплатном <b>{free}</b>\n\n"
            f"🎁 Пробный {config.TRIAL_DAYS} дн. даётся сразу, без одобрения, если:\n"
            f"• одновременно на пробном меньше <b>{st['max_trials']}</b> чатов\n"
            f"• в группе от <b>{st['min_members']}</b> участников (меньше: сразу бесплатный)\n"
            "• чат и человек ещё не брали пробный\nИначе приходит заявка тебе, как раньше.\n\n"
            f"🆓 Бесплатный: нейросеть <b>{st['free_ai'] or 'выключена'}</b>"
            + (" ответов в день" if st["free_ai"] else "") + ", остальное работает.\n"
            f"📣 Напоминать про платную: <b>{st['nudges']}</b> раз в день\n"
            f"🎭 Общий характер для бесплатных: <i>{esc(st['free_persona'][:200]) or 'свой у каждого чата'}</i>")
    def row(key, label, fmt="{}"):
        return [(("✓ " if st[key] == v else "") + label + " " + fmt.format(v), f"cfg:pl:{key}:{v}") for v in PLAN_STEPS[key]]
    await show(target, text, kb([[("Пробных одновременно:", "noop")], row("max_trials", ""),
                                 [("Мин. участников:", "noop")], row("min_members", ""),
                                 [("ИИ бесплатным в день:", "noop")], row("free_ai", ""),
                                 [("Напоминаний в день:", "noop")], row("nudges", ""),
                                 [("🎭 Общий характер для бесплатных", "cfg:pl:persona")],
                                 [("⬅️ Настройки", "cfg:menu"), BACK_MENU]]))


@router.callback_query(F.data == "cfg:pl")
async def cb_plans(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _plans_screen(cb)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("cfg:pl:"))
async def cb_plan_value(cb: CallbackQuery, state: FSMContext) -> None:
    from bot.services import plans
    parts = cb.data.split(":")
    if parts[2] == "persona":
        await state.set_state(PlanPersona.value)
        return await show(cb, "🎭 <b>Общий характер для бесплатных чатов</b>\n\nОн работает, только если бесплатным "
                              "дана квота нейросети. Пришли текст или минус <code>-</code>, чтобы у каждого чата был "
                              "свой.", kb([[("Отмена", "cfg:pl")]]))
    key, value = parts[2], int(parts[3])
    if key in PLAN_STEPS and value in PLAN_STEPS[key]:
        await plans.set_value(key, value)
    await _plans_screen(cb)


@router.message(PlanPersona.value, F.text)
async def on_plan_persona(message: Message, state: FSMContext) -> None:
    from bot.services import plans
    value = "" if message.text.strip() == "-" else message.text.strip()[:3000]
    await plans.set_value("free_persona", value)
    await state.clear()
    await message.answer("✅ Сохранил", reply_markup=kb([[("⬅️ Пробный и бесплатный", "cfg:pl")]]))
