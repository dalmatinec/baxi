"""Меню команд по кнопке /: своё в личке, в группах для всех и для админов групп, у владельца."""

import logging

from aiogram import Bot
from aiogram.types import (BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats,
                           BotCommandScopeAllPrivateChats, BotCommandScopeChat)

from bot import config

log = logging.getLogger(__name__)

PRIVATE = [("start", "Главное меню"), ("profile", "Профиль: монеты, питомец, магазин"),
           ("mychats", "Мои чаты: настроить бота"), ("ads", "Реклама в чатах"),
           *([("mybot", "Свой бот")] if config.IS_MAIN else []),
           ("support", "Поддержка"), ("paysupport", "Вопрос по оплате"), ("terms", "Правила и оплата")]
# в меню по кнопке / только главное, остальные команды в /games (там они нажимаются прямо из текста)
GROUP = [("games", "Все игры и команды"), ("me", "Мой ранг и монеты"), ("dice", "Дуэль костей"),
         ("bonus", "Бонус дня"), ("pet", "Мой питомец"), ("quiz", "Викторина"), ("results", "Итоги дня")]
ADMIN = [("settings", "Настройки бота в этом чате"), ("summary", "Что тут было"), ("call", "Зазывала"),
         ("quiet", "Помолчать час")]
OWNER = [("admin", "Админка"), ("start", "Меню как у людей"), ("mychats", "Мои чаты"), ("cancel", "Отменить ввод")]


def _cmds(items: list[tuple[str, str]]) -> list[BotCommand]:
    return [BotCommand(command=c, description=d) for c, d in items]


async def set_commands(bot: Bot) -> None:
    """Меню команд по кнопке /: в личке, в группах для всех и отдельно для админов групп."""
    try:
        await bot.set_my_commands(_cmds(PRIVATE), scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(_cmds(GROUP), scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(_cmds(ADMIN + GROUP), scope=BotCommandScopeAllChatAdministrators())
        for owner in config.OWNER_IDS:
            await bot.set_my_commands(_cmds(OWNER), scope=BotCommandScopeChat(chat_id=owner))
    except Exception as exc:
        log.warning("Команды не установились: %s", exc)


