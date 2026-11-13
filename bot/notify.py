"""Сообщения владельцам бота в личку."""

import logging

from aiogram import Bot

from bot import config

log = logging.getLogger(__name__)


async def owners(bot: Bot, text: str) -> None:
    for owner in config.OWNER_IDS:
        try:
            await bot.send_message(owner, text, parse_mode="HTML")
        except Exception as exc:
            log.info("Владелец %s не получил уведомление (не запускал бота?): %s", owner, exc)
