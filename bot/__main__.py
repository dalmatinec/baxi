"""Запуск: python -m bot"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot import ai, config, db, handlers
from bot.middlewares import GroupTracker
from bot.services.out import sanitize_requests
from bot.services import adorders, ads, daily, emoji, stars
from bot.services.commands_menu import set_commands

log = logging.getLogger("bot")

async def main() -> None:
    config.check()
    logging.basicConfig(level=config.LOG_LEVEL,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    await db.connect()
    await stars.refresh_looks()
    bot = Bot(config.BOT_TOKEN)
    bot.session.middleware(sanitize_requests)  # никаких длинных тире и ёлочек ни в одном сообщении
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(GroupTracker())
    dp.include_router(handlers.setup())

    me = await bot.me()
    if not config.DEFAULT_NAME:
        config.DEFAULT_NAME = me.first_name or "бот"
        fixed = await db.fix_legacy_name(config.DEFAULT_NAME)
        if fixed:
            log.info("Переименовал бота из «%s» в «%s» в %s чатах", config.LEGACY_NAME, config.DEFAULT_NAME, fixed)
    log.info("Бот @%s запущен. ИИ: %s", me.username,
             "включён" if ai.enabled() else "выключен (нет AI_API_KEY)")
    await set_commands(bot)
    await emoji.load()

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
