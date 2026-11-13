"""Общее для админки: главное меню, клавиатуры, показ экранов."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from bot import ai, config, db

router = Router(name="admin-common")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """[[('текст', 'callback'), ...], ...] → клавиатура."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows if row])


BACK_MENU = ("⬅️ Меню", "menu")


async def show(target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Callback: правим текущее сообщение. Не получается (это стикер, фото): шлём новое."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup,
                                           link_preview_options=NO_PREVIEW)
        except Exception as exc:
            if "message is not modified" not in str(exc):
                await target.message.answer(text, parse_mode="HTML", reply_markup=markup,
                                            link_preview_options=NO_PREVIEW)
        try:
            await target.answer()
        except Exception:
            pass  # на кнопку уже ответили раньше
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=markup, link_preview_options=NO_PREVIEW)


def onoff(v) -> str:
    return "✅" if v else "❌"


def pct(v: float) -> str:
    return f"{round(v * 100)}%"


async def menu_text() -> str:
    chats = await db.list_chats()
    ads = await db.list_ads()
    spent = await db.spent_today()
    if not ai.enabled():
        ai_line = "🤖 ИИ: <b>выключен</b> (нет AI_API_KEY в .env), бот отвечает фразами"
    else:
        ai_line = f"🤖 ИИ: <code>{config.AI_MODEL}</code>, сегодня ${spent:.3f} из ${config.DAILY_LIMIT_USD:.2f}"
    return ("⚙️ <b>Админка</b>\n\n"
            f"💬 Чатов: <b>{len(chats)}</b>\n"
            f"📣 Рекламных постов: <b>{len(ads)}</b> (включено {sum(1 for a in ads if a['enabled'])})\n"
            f"{ai_line}")


MENU_KB = kb([
    [("💬 Чаты", "ch:list"), ("📣 Реклама", "ad:list")],
    [("🗯 Фразы и стикеры", "ph:menu"), ("📊 Расход", "spend")],
])


@router.message(CommandStart())
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message, await menu_text(), MENU_KB)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show(message, "Отменил.\n\n" + await menu_text(), MENU_KB)


@router.callback_query(lambda c: c.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, await menu_text(), MENU_KB)


@router.callback_query(lambda c: c.data == "spend")
async def cb_spend(cb: CallbackQuery) -> None:
    rows = await db.spend_report(30)
    lines = [f"{r['day']}: ${r['usd']:.3f} · {r['requests']} запр." for r in rows[:7]]
    month = sum(r["usd"] for r in rows)
    text = ("📊 <b>Расход на ИИ</b>\n\n"
            f"Модель: <code>{config.AI_MODEL}</code>\n"
            f"Лимит в сутки: <b>${config.DAILY_LIMIT_USD:.2f}</b> (меняется в .env, DAILY_LIMIT_USD)\n"
            f"За 30 дней: <b>${month:.3f}</b>\n\n"
            + ("\n".join(lines) if lines else "Пока ни одного запроса.")
            + "\n\nКогда лимит на сегодня кончается, бот до полуночи отвечает фразами из базы.")
    await show(cb, text, kb([[BACK_MENU]]))
