from __future__ import annotations

import asyncio
import logging
import sys

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from admin_handlers import setup_admin_router
from config import load_settings
from db import Database
from services import broadcast_loop
from miniapp import MiniAppServer
from states import SessionStore
from user_handlers import setup_user_router


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    polling_lock = await asyncpg.connect(settings.database_url)
    try:
        lock_acquired = await polling_lock.fetchval(
            "SELECT pg_try_advisory_lock(hashtext($1))",
            "refer-new-bot:telegram-polling",
        )
        if not lock_acquired:
            logging.getLogger(__name__).error(
                "Another bot instance already owns the Telegram polling lock; exiting."
            )
            return

        db = Database(settings.database_url)
        await db.connect()
        bot = Bot(settings.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    miniapp_server = MiniAppServer(
        db,
        bot,
        settings.token,
        settings.verification_hash_secret,
        settings.ipinfo_token,
        settings.trust_proxy,
        settings.verification_max_age,
        settings.verification_rate_window,
        settings.verification_max_attempts,
        settings.verification_max_api_requests,
        settings.reputation_cache_seconds,
    )
    sessions = SessionStore()
    worker: asyncio.Task[None] | None = None

    async def wake_broadcast_worker() -> None:
        # The persistent queue is continuously consumed by the startup worker.
        return None

    dp.include_router(setup_admin_router(db, bot, sessions, wake_broadcast_worker))
    dp.include_router(
        setup_user_router(db, bot, sessions, settings.bot_name, settings.miniapp_url)
    )
    worker = asyncio.create_task(broadcast_loop(bot, db))
    try:
        try:
            await miniapp_server.start(settings.web_host, settings.web_port)
        except Exception:
            logging.getLogger(__name__).exception("Mini App server could not start; bot will continue")
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await miniapp_server.stop()
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await bot.session.close()
        await db.close()
    finally:
        await polling_lock.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
