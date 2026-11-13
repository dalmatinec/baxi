from aiogram import Router

from bot.handlers import adshop, admin, commands, fun, games, group, members, private, stars


def setup() -> Router:
    """Порядок важен: сначала админка и служебные события, потом игры, потом обычная болтовня."""
    root = Router(name="root")
    root.include_routers(admin.router, members.router, commands.router, fun.router, games.router, group.router, stars.router, adshop.router,
                         private.router)
    return root
