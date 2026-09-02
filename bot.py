from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from admin_handlers import setup_admin_router
from config import load_settings
from db import Database
from services import broadcast_loop
from states import SessionStore
from user_handlers import setup_user_router


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    db = Database(settings.database_url)
    await db.connect()
    bot = Bot(settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    sessions = SessionStore()
    worker: asyncio.Task[None] | None = None

    async def wake_broadcast_worker() -> None:
        # The persistent queue is continuously consumed by the startup worker.
        return None

    dp.include_router(setup_admin_router(db, bot, sessions, wake_broadcast_worker))
    dp.include_router(setup_user_router(db, bot, sessions, settings.bot_name))
    worker = asyncio.create_task(broadcast_loop(bot, db))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
