"""Экономика: монеты, уровни, питомцы, кости.

  chat.py     команды в чатах: кошелёк, бонус, питомец и корм, топы, кости, переводы
  profile.py  личка бота: профиль у каждого свой, магазин, пополнение звёздами и криптой, как заработать
  common.py   общее: тексты профиля и топов, карточка питомца, кнопки
Логика без Telegram: bot/economy/."""

from aiogram import Router

from bot.handlers.economy import chat, profile

router = Router(name="economy")
router.include_routers(chat.router, profile.router)
