"""Админка в личке с ботом. Доступна только владельцам из OWNER_IDS."""

from aiogram import F, Router

from bot import config
from bot.handlers.admin import (ads, chats, clients, common, economy, orders, owner_cmds, people, phrases, screens,
                                settings, shop, support)

router = Router(name="admin")
_owner = F.from_user.id.in_(config.OWNER_IDS)
router.message.filter(F.chat.type == "private", _owner)
router.callback_query.filter(_owner)
router.include_routers(common.router, owner_cmds.router, chats.router, phrases.router, ads.router, support.router,
                      screens.router, orders.router, shop.router, people.router, settings.router, economy.router)
if config.IS_MAIN:
    router.include_router(clients.router)
