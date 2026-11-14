"""Поддержка: обращения списком, как переписки. Новые сверху, у каждого вся история.
Владелец жмёт «Ответить» и пишет ответ, бот пересылает его человеку."""

import time

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import db
from bot.handlers.admin.common import BACK_MENU, kb, show
from bot.handlers.private import describe_dm
from bot.textutil import esc, short

router = Router(name="admin-support")


class SupportReply(StatesGroup):
    message = State()


def ago(ts: float) -> str:
    s = time.time() - ts
    if s < 3600:
        return f"{max(1, int(s // 60))} мин"
    if s < 86400:
        return f"{int(s // 3600)} ч"
    return f"{int(s // 86400)} дн"


async def inbox(target) -> None:
    threads = await db.support_threads()
    new = sum(1 for t in threads if t["status"] == "new")
    if not threads:
        text = "🆘 <b>Поддержка</b>\n\nОбращений нет. Когда кто-то напишет в поддержку, оно появится здесь."
    else:
        lines = [f"🆘 <b>Поддержка</b> · новых: {new}" if new else "🆘 <b>Поддержка</b>", ""]
        for t in threads[:12]:
            last = (await db.support_msgs(t["user_id"], 1))
            mark = "🟢" if t["status"] == "new" else "✅"
            topic = f" · {esc(t['topic'])}" if t["topic"] else ""
            lines.append(f"{mark} <b>{esc(t['name'] or str(t['user_id']))}</b>{topic} · {ago(t['last_ts'])}")
            if last:
                lines.append(f"<i>{esc(short(last[0]['text'], 70))}</i>")
            lines.append("")
        text = "\n".join(lines).strip()
    rows = [[(short(t["name"] or str(t["user_id"]), 18), f"su:t:{t['user_id']}",
              "primary" if t["status"] == "new" else None) for t in threads[i:i + 2]]
            for i in range(0, min(len(threads), 12), 2)]
    await show(target, text, kb(rows + [[("📁 Архив", "su:arch")], [BACK_MENU]]))


@router.callback_query(F.data == "su:list")
async def cb_inbox(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await inbox(cb)


@router.callback_query(F.data == "su:arch")
async def cb_archive(cb: CallbackQuery) -> None:
    threads = await db.support_threads(closed=True)
    rows = [[(f"📁 {short(t['name'] or str(t['user_id']), 30)} · {ago(t['last_ts'])}", f"su:t:{t['user_id']}")]
            for t in threads[:20]]
    await show(cb, "📁 <b>Закрытые обращения</b>" if threads else "📁 Архив пуст",
               kb(rows + [[("⬅️ Все обращения", "su:list"), BACK_MENU]]))


async def thread(target, user_id: int) -> None:
    t = await db.support_thread(user_id)
    msgs = await db.support_msgs(user_id, 10)
    from datetime import datetime
    from bot import config
    name = esc(t["name"] if t else str(user_id))
    user = f" @{esc(t['username'])}" if t and t["username"] else ""
    topic = f" · {esc(t['topic'])}" if t and t["topic"] else ""
    lines = [f"💬 <b>{name}</b>{user}{topic}", f"<code>{user_id}</code>", ""]
    for m in msgs:
        when = datetime.fromtimestamp(m["ts"], config.TZ).strftime("%d.%m %H:%M")
        who = "🙋" if m["direction"] == "in" else "👑 ты:"
        lines.append(f"<i>{when}</i> {who} {esc(short(m['text'], 300))}")
    rows = [[("✍️ Ответить", f"sup:{user_id}", "primary"), ("✅ Закрыть", f"su:x:{user_id}")]]
    if t and t["username"]:
        rows.append([(f"💬 Написать @{t['username']} напрямую", f"https://t.me/{t['username']}")])
    rows.append([("⬅️ Все обращения", "su:list"), BACK_MENU])
    await show(target, "\n".join(lines), kb(rows))


@router.callback_query(F.data.startswith("su:t:"))
async def cb_thread(cb: CallbackQuery) -> None:
    await thread(cb, int(cb.data.split(":")[2]))


@router.callback_query(F.data.startswith("su:x:"))
async def cb_close(cb: CallbackQuery) -> None:
    await db.support_close(int(cb.data.split(":")[2]))
    await cb.answer("✅ Закрыто")
    await inbox(cb)


@router.callback_query(F.data.startswith("sup:"))
async def cb_reply(cb: CallbackQuery, state: FSMContext) -> None:
    user_id = int(cb.data.split(":")[1])
    await state.set_state(SupportReply.message)
    await state.update_data(user_id=user_id)
    t = await db.support_thread(user_id)
    who = esc(t["name"]) if t and t["name"] else f"<code>{user_id}</code>"
    await cb.message.answer(f"✍️ Напиши ответ для {who} (текст, фото, что угодно) или /cancel", parse_mode="HTML")
    await cb.answer()


@router.message(SupportReply.message)
async def on_reply(message: Message, bot: Bot, state: FSMContext) -> None:
    user_id = (await state.get_data())["user_id"]
    await state.clear()
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🆘 Написать ещё", callback_data="act:support", style="primary"),
        InlineKeyboardButton(text="⬅️ В меню", callback_data="sc:start")]])
    try:
        await bot.send_message(user_id, "💬 <b>Сообщение от поддержки бота:</b>", parse_mode="HTML")
        await bot.copy_message(user_id, message.chat.id, message.message_id, reply_markup=markup)
    except Exception as exc:
        if "initiate" in str(exc) or "blocked" in str(exc) or "chat not found" in str(exc):
            return await message.answer("Не доставлено: человек ни разу не запускал бота в личке или заблокировал "
                                        "его. Напиши ему напрямую со своего аккаунта (ссылка в карточке чата).")
        return await message.answer(f"Не доставлено: {str(exc)[:200]}")
    await db.support_add(user_id, "", "", "", "out", describe_dm(message))
    await message.answer("✅ Ответ доставлен", reply_markup=kb([[("💬 Переписка", f"su:t:{user_id}"),
                                                                ("🆘 Все обращения", "su:list")]]))
