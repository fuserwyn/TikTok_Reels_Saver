from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.config import (
    TELEGRAM_BOT_VIDEO_MAX_BYTES,
    load_database_url,
    load_mtproto_app_credentials,
    load_settings,
    load_stats_admin_ids,
    load_telethon_session_string,
    load_ytdlp_autoupdate_hours,
)
from bot.db import create_pool, init_schema
from bot.handlers import build_router
from bot.telethon_upload import TELEGRAM_USER_VIDEO_MAX_BYTES


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

    token, max_bytes, max_upload_explicit = load_settings()
    database_url = load_database_url()
    stats_admins = load_stats_admin_ids()
    ytdlp_autoupdate_hours = load_ytdlp_autoupdate_hours()
    pool = None
    updater_task: asyncio.Task[None] | None = None
    user_client: TelegramClient | None = None

    mt = load_mtproto_app_credentials()
    session_str = load_telethon_session_string()
    if mt and session_str:
        api_id, api_hash = mt
        try:
            user_client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await user_client.connect()
            if await user_client.is_user_authorized():
                user_me = await user_client.get_me()
                log.info(
                    "Telethon user id %s — отправка видео >50 МБ от пользователя.",
                    user_me.id,
                )
                if (
                    not max_upload_explicit
                    and max_bytes <= TELEGRAM_BOT_VIDEO_MAX_BYTES
                ):
                    max_bytes = TELEGRAM_USER_VIDEO_MAX_BYTES
                    log.info(
                        "Лимит скачивания — до %s МБ (сессия Telethon; MAX_UPLOAD_BYTES не задан).",
                        max_bytes // (1024 * 1024),
                    )
                elif max_upload_explicit and max_bytes <= TELEGRAM_BOT_VIDEO_MAX_BYTES:
                    log.warning(
                        "MAX_UPLOAD_BYTES ≤ 50 МБ при работающей сессии Telethon — "
                        "ролики крупнее не скачаются; убери переменную или подними лимит.",
                    )
            else:
                log.error("TELEGRAM_SESSION недействителен — большие файлы отключены.")
                await user_client.disconnect()
                user_client = None
        except Exception:
            log.exception("Telethon: не удалось подключиться.")
            if user_client is not None:
                try:
                    await user_client.disconnect()
                except Exception:
                    pass
                user_client = None
    elif session_str and not mt:
        log.warning(
            "TELEGRAM_SESSION задан без API_ID/API_HASH — большие файлы отключены.",
        )

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
    dp.include_router(build_router(max_bytes, pool, stats_admins, user_client))

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
        if user_client is not None:
            await user_client.disconnect()
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
