from aiogram import Router

from bot.handlers import admin, games, group, members, private


def setup() -> Router:
    """Порядок важен: сначала админка и служебные события, потом игры, потом обычная болтовня."""
    root = Router(name="root")
    root.include_routers(admin.router, members.router, games.router, group.router, private.router)
    return root
