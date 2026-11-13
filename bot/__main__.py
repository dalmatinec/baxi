"""Запуск: python -m bot"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from bot import ai, config, db, handlers
from bot.middlewares import GroupTracker
from bot.services.out import sanitize_requests
from bot.services import adorders, ads, daily

log = logging.getLogger("bot")


async def main() -> None:
    config.check()
    logging.basicConfig(level=config.LOG_LEVEL,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    await db.connect()
    bot = Bot(config.BOT_TOKEN)
    bot.session.middleware(sanitize_requests)  # никаких длинных тире и ёлочек ни в одном сообщении
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(GroupTracker())
    dp.include_router(handlers.setup())

    me = await bot.me()
    log.info("Бот @%s запущен. ИИ: %s", me.username,
             f"{config.AI_MODEL} через {config.AI_BASE_URL}" if ai.enabled() else "выключен (нет AI_API_KEY)")
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Меню"),
                                   BotCommand(command="support", description="Поддержка"),
                                   BotCommand(command="paysupport", description="Вопрос по оплате")],
                                  scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands([BotCommand(command="games", description="Что я умею"),
                                    BotCommand(command="quiz", description="Викторина"),
                                    BotCommand(command="top", description="Топ репутации")],
                                  scope=BotCommandScopeAllGroupChats())
        for owner in config.OWNER_IDS:  # владельцам в личке ещё и /admin
            await bot.set_my_commands([BotCommand(command="admin", description="Админка"),
                                       BotCommand(command="start", description="Меню как у людей"),
                                       BotCommand(command="cancel", description="Отменить ввод")],
                                      scope=BotCommandScopeChat(chat_id=owner))
    except Exception as exc:
        log.warning("Команды не установились: %s", exc)

    scheduler = asyncio.create_task(ads.run_scheduler(bot))
    planner = asyncio.create_task(daily.run_scheduler(bot))
    orders = asyncio.create_task(adorders.run_scheduler(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.cancel()
        planner.cancel()
        orders.cancel()
        await ai.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code not in (None, 0):
            raise
