from __future__ import annotations

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from social_video_fetch import ShortVideoDownload

TELEGRAM_USER_VIDEO_MAX_BYTES = 2 * 1024 * 1024 * 1024


async def send_large_video_as_user(
    client: Client,
    chat_id: int,
    clip: ShortVideoDownload,
    caption: str,
    open_label: str,
    open_url: str,
    file_name: str | None = None,
) -> None:
    path = clip.file_path
    size = path.stat().st_size if path.is_file() else 0
    if size > TELEGRAM_USER_VIDEO_MAX_BYTES:
        raise OSError(f"Файл слишком большой для Telegram ({size} байт).")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton(open_label, url=open_url)]])
    duration = clip.actual_duration or clip.duration or None
    kwargs: dict = {
        "caption": caption[:1024],
        "parse_mode": ParseMode.HTML,
        "supports_streaming": True,
        "reply_markup": kb,
    }
    if duration is not None and duration > 0:
        kwargs["duration"] = int(duration)
    if clip.width is not None and clip.height is not None:
        kwargs["width"] = clip.width
        kwargs["height"] = clip.height

    if file_name:
        kwargs["file_name"] = file_name

    await client.send_video(chat_id, video=str(path), **kwargs)
