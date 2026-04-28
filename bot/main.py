from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import load_database_url, load_settings, load_stats_admin_ids
from bot.db import create_pool, init_schema
from bot.handlers import build_router


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    _configure_logging()
    log = logging.getLogger("social_video_bot")

    token, max_bytes = load_settings()
    database_url = load_database_url()
    stats_admins = load_stats_admin_ids()
    pool = None
    if database_url:
        pool = await create_pool(database_url)
        await init_schema(pool)
    else:
        log.warning(
            "DATABASE_URL не задан — учёт пользователей в PostgreSQL отключён.",
        )

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(build_router(max_bytes, pool, stats_admins))

    me = await bot.get_me()
    log.info("Bot @%s started.", me.username)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if pool is not None:
            await pool.close()
            log.info("PostgreSQL pool closed.")


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
