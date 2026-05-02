from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from typing import FrozenSet

import asyncpg
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import TELEGRAM_BOT_VIDEO_MAX_BYTES
from bot.db import fetch_user_stats, increment_download_request
from bot.pyrogram_upload import send_large_video_as_user
from social_video_fetch import (
    SocialVideoError,
    SocialVideoTooLargeError,
    compress_clip_to_max_bytes,
    download_social_video,
    find_instagram_reel_url,
    find_tiktok_url,
)

logger = logging.getLogger(__name__)


@dataclass
class HandlerContext:
    max_upload_bytes: int
    pool: asyncpg.Pool | None
    stats_admin_ids: FrozenSet[int]
    user_client: Client | None


def _user_text_for_social_error(exc: SocialVideoError) -> str:
    s = str(exc).lower()
    if "tiktok" in s:
        return (
            "Не вышло скачать с TikTok. Попробуй полную ссылку @…/video/…, обнови "
            "yt-dlp в образе или укажи YT_DLP_COOKIEFILE / cookies c сайта."
        )
    if "instagram" in s or "reel" in s:
        return (
            "Не вышло скачать с Reels. Обнови образ (свежий yt-dlp) — у Instagram правки "
            "выходят часто. С IP хостинга часто нужны cookies и YT_DLP_COOKIEFILE. "
            "Или открой ролик в браузере без входа — если там не идёт, бот не скачает."
        )
    return (
        "Не вышлось скачать. Попробуй другую ссылку, обнови yt-dlp в контейнере "
        "или укажи YT_DLP_COOKIEFILE (Netscape cookies.txt с нужного сайта)."
    )


def register_handlers(bot: Client, ctx: HandlerContext) -> None:
    @bot.on_message(filters.private & filters.command("stats"))
    async def on_stats(_: Client, message: Message) -> None:
        uid = message.from_user.id if message.from_user else 0
        if uid not in ctx.stats_admin_ids:
            return
        if ctx.pool is None:
            await message.reply_text("База данных не подключена (нет DATABASE_URL).")
            return
        total_users, total_requests = await fetch_user_stats(ctx.pool)
        await message.reply_text(
            f"Пользователей в базе: {total_users}\n"
            f"Всего запросов (скачиваний): {total_requests}",
        )

    @bot.on_message(filters.private & filters.command("start"))
    async def on_start(_: Client, message: Message) -> None:
        await message.reply_text(
            "Ссылка на TikTok или Reels в этот чат — пришлю видео.",
        )

    @bot.on_message(filters.private & filters.command("help"))
    async def on_help(_: Client, message: Message) -> None:
        await message.reply_text(
            "Ссылка на TikTok или Reels в этот чат — пришлю видео.",
        )

    @bot.on_message(filters.private & filters.text & ~filters.regex("^/"))
    async def on_text(client: Client, message: Message) -> None:
        text = message.text or ""
        url = find_tiktok_url(text) or find_instagram_reel_url(text)
        if not url:
            await message.reply_text(
                "Нужна ссылка TikTok (tiktok.com, vm.tiktok.com, …) "
                "или Reels (instagram.com/reel/…).",
            )
            return

        u = message.from_user
        try:
            await increment_download_request(ctx.pool, u.id if u else 0, u.username if u else None)
        except Exception:
            logger.exception("increment_download_request failed")

        status = await message.reply_text("Качаю…")
        await client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        try:
            clip = await download_social_video(url, ctx.max_upload_bytes)
        except SocialVideoTooLargeError as exc:
            await status.edit_text(
                f"Файл ~{exc.size_bytes / 1024 / 1024:.1f} МБ — больше лимита скачивания "
                f"({exc.limit_bytes // 1024 // 1024} МБ). Если в Railway задан MAX_UPLOAD_BYTES=52428800, "
                "убери переменную (при живой сессии пользователя Pyrogram лимит поднимется сам) или задай больший; "
                "без TELEGRAM_SESSION качаем не больше ~50 МБ."
            )
            return
        except SocialVideoError as exc:
            logger.warning("download failed: %s", exc)
            await status.edit_text(_user_text_for_social_error(exc))
            return
        except Exception:
            logger.exception("unexpected download error")
            await status.edit_text("Внутренняя ошибка, попробуй позже.")
            return

        low = clip.webpage_url.lower()
        if "instagram.com" in low or "instagr.am" in low:
            open_label, open_url = "Открыть в Instagram", clip.webpage_url
        elif "tiktok.com" in low:
            open_label, open_url = "Открыть в TikTok", clip.webpage_url
        else:
            open_label, open_url = "Открыть", clip.webpage_url

        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=open_label, url=open_url)]]
        )

        try:
            safe = re.sub(r"[^\w\-]+", "_", clip.title)[:80] or "video"
            vext = clip.file_path.suffix.lower()
            if vext not in (".mp4", ".webm"):
                vext = ".mp4"
            me = await client.get_me()
            if me and me.username:
                credit = f"\n\nВидео сгенерировано ботом @{html.escape(me.username)}"
            else:
                credit = ""
            cap_title = html.escape(clip.title)
            cap_artist = html.escape(clip.artist or "")
            caption = f"<b>{cap_title}</b>\n{cap_artist}{credit}"
            file_size = clip.file_path.stat().st_size
            if file_size > TELEGRAM_BOT_VIDEO_MAX_BYTES:
                await status.edit_text("Сжимаю под лимит Telegram (~50 МБ)…")
                await client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
                await asyncio.to_thread(
                    compress_clip_to_max_bytes,
                    clip,
                    TELEGRAM_BOT_VIDEO_MAX_BYTES,
                )
                file_size = clip.file_path.stat().st_size
                vext = clip.file_path.suffix.lower()
                if vext not in (".mp4", ".webm"):
                    vext = ".mp4"

            if file_size <= TELEGRAM_BOT_VIDEO_MAX_BYTES:
                send_kw: dict = {
                    "video": str(clip.file_path),
                    "file_name": f"{safe}{vext}",
                    "caption": caption,
                    "duration": clip.actual_duration or clip.duration or 0,
                    "supports_streaming": True,
                    "reply_markup": kb,
                    "reply_to_message_id": message.id,
                }
                if clip.width is not None and clip.height is not None:
                    send_kw["width"] = clip.width
                    send_kw["height"] = clip.height
                await client.send_video(message.chat.id, **send_kw)
            elif ctx.user_client is not None:
                try:
                    await send_large_video_as_user(
                        ctx.user_client,
                        message.chat.id,
                        clip,
                        caption,
                        open_label,
                        open_url,
                        file_name=f"{safe}{vext}",
                    )
                except RPCError:
                    logger.exception("pyrogram user send failed (RPC)")
                    await status.edit_text(
                        "Скачал большое видео, но не удалось отправить через личный аккаунт (Telegram). "
                        "Часто мешают настройки приватности — напиши аккаунту сессии в личку или попробуй позже."
                    )
                    return
            else:
                await status.edit_text(
                    f"Файл ~{file_size / 1024 / 1024:.1f} МБ — перекодированием в ~50 МБ не удалось. "
                    "Добавь TELEGRAM_SESSION (Pyrogram), чтобы отправить крупный оригинал. См. .env.example."
                )
                return

            try:
                await status.delete()
            except Exception:
                pass
        except Exception:
            logger.exception("send video failed")
            await status.edit_text("Скачал, но не удалось отправить видео.")
        finally:
            clip.cleanup()
