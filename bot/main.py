from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import (
    load_database_url,
    load_settings,
    load_stats_admin_ids,
    load_ytdlp_autoupdate_hours,
)
from bot.db import create_pool, init_schema
from bot.handlers import build_router


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


def _update_ytdlp_sync() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "yt-dlp"],
        check=True,
        capture_output=True,
        text=True,
        timeout=1800,
    )


async def _ytdlp_autoupdate_loop(interval_hours: float) -> None:
    log = logging.getLogger("social_video_bot")
    interval_seconds = interval_hours * 3600
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(_update_ytdlp_sync)
            log.info("yt-dlp auto-update finished successfully.")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("yt-dlp auto-update failed")


async def run() -> None:
    _configure_logging()
    log = logging.getLogger("social_video_bot")

    token, max_bytes = load_settings()
    database_url = load_database_url()
    stats_admins = load_stats_admin_ids()
    ytdlp_autoupdate_hours = load_ytdlp_autoupdate_hours()
    pool = None
    updater_task: asyncio.Task[None] | None = None
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
    if ytdlp_autoupdate_hours > 0:
        updater_task = asyncio.create_task(_ytdlp_autoupdate_loop(ytdlp_autoupdate_hours))
        log.info("yt-dlp auto-update enabled: every %.2f hours.", ytdlp_autoupdate_hours)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        if updater_task is not None:
            updater_task.cancel()
            try:
                await updater_task
            except asyncio.CancelledError:
                pass
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
