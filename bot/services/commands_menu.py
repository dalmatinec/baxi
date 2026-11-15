"""Меню команд по кнопке /: своё в личке, в группах для всех и для админов групп, у владельца."""

import logging

from aiogram import Bot
from aiogram.types import (BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats,
                           BotCommandScopeAllPrivateChats, BotCommandScopeChat)

from bot import config

log = logging.getLogger(__name__)

PRIVATE = [("start", "Главное меню"), ("mychats", "Мои чаты: настроить бота"), ("shop", "Магазин"),
           ("support", "Поддержка"), ("paysupport", "Вопрос по оплате")]
GROUP = [("games", "Игры и команды"), ("results", "Итоги дня"), ("top", "Топ репутации"), ("quiz", "Викторина"),
         ("couple", "Пара дня"), ("predict", "Предсказание"), ("ship", "Совместимость (ответом)"),
         ("rep", "Моя репутация"), ("joke", "Шутка"), ("roast", "Прожарка (ответом)"), ("bdays", "Дни рождения"),
         ("wallet", "Кошелёк и уровень"), ("bonus", "Бонус дня"), ("shop", "Магазин за монеты"),
         ("pet", "Мой питомец"), ("pets", "Топ питомцев"), ("rich", "Богачи чата"), ("dice", "Кости на монеты (ответом)"),
         ("donors", "Топ донатеров")]
ADMIN = [("settings", "Настройки бота в этом чате"), ("summary", "Что тут было"), ("pair", "Как вам пара"),
         ("quiet", "Помолчать час"), ("talk", "Снова болтать"), ("call", "Зазывала"), ("stopcall", "Остановить зазывалу")]
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


