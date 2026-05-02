from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from pyrogram import Client, idle
from pyrogram.enums import ParseMode

from bot.config import (
    TELEGRAM_BOT_VIDEO_MAX_BYTES,
    load_database_url,
    load_mtproto_app_credentials,
    load_settings,
    load_stats_admin_ids,
    load_user_session_string,
    load_ytdlp_autoupdate_hours,
)
from bot.db import create_pool, init_schema
from bot.handlers import HandlerContext, register_handlers
from bot.pyrogram_upload import TELEGRAM_USER_VIDEO_MAX_BYTES


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
    mt = load_mtproto_app_credentials()
    if not mt:
        raise RuntimeError(
            "Задай API_ID и API_HASH (my.telegram.org) — Pyrogram-боту они нужны всегда, как в WAV-проекте.",
        )
    api_id, api_hash = mt

    database_url = load_database_url()
    stats_admins = load_stats_admin_ids()
    ytdlp_autoupdate_hours = load_ytdlp_autoupdate_hours()
    pool = None
    updater_task: asyncio.Task[None] | None = None
    user_client: Client | None = None

    session_str = load_user_session_string()
    if session_str:
        uc = Client(
            "large_video_user",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_str,
            in_memory=True,
        )
        try:
            await uc.start()
            ume = await uc.get_me()
            if ume is not None:
                log.info(
                    "Pyrogram user id %s — видео >50 МБ уходят от этого аккаунта.",
                    ume.id,
                )
                user_client = uc
                if not max_upload_explicit and max_bytes <= TELEGRAM_BOT_VIDEO_MAX_BYTES:
                    max_bytes = TELEGRAM_USER_VIDEO_MAX_BYTES
                    log.info(
                        "Лимит скачивания — до %s МБ (TELEGRAM_SESSION; MAX_UPLOAD_BYTES не задан).",
                        max_bytes // (1024 * 1024),
                    )
                elif max_upload_explicit and max_bytes <= TELEGRAM_BOT_VIDEO_MAX_BYTES:
                    log.warning(
                        "MAX_UPLOAD_BYTES ≤ 50 МБ при работающей пользовательской сессии — "
                        "ролики крупнее не скачаются; убери переменную или подними лимит.",
                    )
            else:
                await uc.stop()
        except Exception:
            log.exception("Pyrogram: пользовательская сессия не подошла.")
            try:
                await uc.stop()
            except Exception:
                pass
            user_client = None
    else:
        log.debug("TELEGRAM_SESSION не задан — только видео до ~50 МБ от бота.")

    if database_url:
        pool = await create_pool(database_url)
        await init_schema(pool)
    else:
        log.warning(
            "DATABASE_URL не задан — учёт пользователей в PostgreSQL отключён.",
        )

    bot = Client(
        "social_video_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
        parse_mode=ParseMode.HTML,
    )
    ctx = HandlerContext(
        max_upload_bytes=max_bytes,
        pool=pool,
        stats_admin_ids=stats_admins,
        user_client=user_client,
    )
    register_handlers(bot, ctx)

    if ytdlp_autoupdate_hours > 0:
        updater_task = asyncio.create_task(_ytdlp_autoupdate_loop(ytdlp_autoupdate_hours))
        log.info("yt-dlp auto-update enabled: every %.2f hours.", ytdlp_autoupdate_hours)

    try:
        async with bot:
            me = await bot.get_me()
            uname = me.username if me else None
            log.info("Bot @%s started.", uname or (me.id if me else "?"))
            await idle()
    finally:
        if updater_task is not None:
            updater_task.cancel()
            try:
                await updater_task
            except asyncio.CancelledError:
                pass
        if user_client is not None:
            try:
                await user_client.stop()
            except Exception:
                log.exception("Ошибка при остановке пользовательского клиента.")
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
