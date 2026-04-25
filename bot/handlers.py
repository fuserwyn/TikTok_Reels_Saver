from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.markdown import hbold

from social_video_fetch import (
    SocialVideoError,
    SocialVideoTooLargeError,
    download_social_video,
    find_instagram_reel_url,
    find_tiktok_url,
    find_youtube_shorts_url,
)

logger = logging.getLogger(__name__)


def _user_text_for_social_error(exc: SocialVideoError) -> str:
    """Короткое объяснение вместо длинного текста от yt-dlp (не светим FAQ в чате)."""
    s = str(exc).lower()
    if "[youtube]" in s:
        if any(
            x in s
            for x in (
                "sign in",
                "not a bot",
                "use --cookies",
                "подтвердите",
                "confirm you",
            )
        ):
            return (
                "YouTube требует куки залогиненного аккаунта (иначе пишет «войдите, чтобы "
                "подтвердить, что вы не бот»). Экспортируй cookies с youtube.com в "
                "Netscape cookies.txt и в Railway/сервере укажи YT_DLP_COOKIEFILE на этот "
                "файл. Подсказка: в wiki yt-dlp — «Exporting YouTube cookies»."
            )
    if "tiktok" in s:
        return (
            "Не вышло скачать с TikTok. Попробуй полную ссылку @…/video/…, обнови "
            "yt-dlp в образе или укажи YT_DLP_COOKIEFILE / cookies c сайта."
        )
    if "instagram" in s or "reel" in s:
        return (
            "Не вышло скачать с Reels. Попробуй ссылку вида instagram.com/reel/… "
            "или укажи YT_DLP_COOKIEFILE."
        )
    return (
        "Не вышлось скачать. Попробуй другую ссылку, обнови yt-dlp в контейнере "
        "или укажи YT_DLP_COOKIEFILE (Netscape cookies.txt с нужного сайта)."
    )


def build_router(max_upload_bytes: int) -> Router:
    router = Router(name="social_video_bot")

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            "Ссылка на TikTok, Reels или YouTube Shorts в этот чат — пришлю видео.",
        )

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await on_start(message)

    @router.message(F.text, F.chat.type == "private")
    async def on_text(message: Message) -> None:
        text = message.text or ""
        url = (
            find_tiktok_url(text)
            or find_instagram_reel_url(text)
            or find_youtube_shorts_url(text)
        )
        if not url:
            await message.answer(
                "Нужна ссылка TikTok, Reels (instagram.com/reel/…) "
                "или YouTube Shorts (youtube.com/shorts/…).",
            )
            return

        status = await message.reply("Качаю…")
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        try:
            clip = await download_social_video(url, max_upload_bytes)
        except SocialVideoTooLargeError as exc:
            await status.edit_text(
                f"Файл ~{exc.size_bytes / 1024 / 1024:.1f} МБ — больше лимита Telegram "
                f"({exc.limit_bytes // 1024 // 1024} МБ)."
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
        elif "youtube.com" in low or "youtu.be" in low:
            open_label, open_url = "Открыть в YouTube", clip.webpage_url
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
            me = await message.bot.get_me()
            if me.username:
                credit = f"\n\nВидео сгенерировано ботом @{me.username}"
            else:
                credit = ""
            caption = f"{hbold(clip.title)}\n{clip.artist}{credit}"
            await message.answer_video(
                video=FSInputFile(clip.file_path, filename=f"{safe}{vext}"),
                caption=caption,
                duration=clip.actual_duration or clip.duration or None,
                supports_streaming=True,
                reply_markup=kb,
            )
            try:
                await status.delete()
            except Exception:
                pass
        except Exception:
            logger.exception("send video failed")
            await status.edit_text("Скачал, но не удалось отправить видео.")
        finally:
            clip.cleanup()

    return router
