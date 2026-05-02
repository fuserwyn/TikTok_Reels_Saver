from __future__ import annotations

from telethon import TelegramClient
from telethon.tl.custom import Button

from social_video_fetch import ShortVideoDownload

TELEGRAM_USER_VIDEO_MAX_BYTES = 2 * 1024 * 1024 * 1024


async def send_large_video_as_user(
    client: TelegramClient,
    chat_id: int,
    clip: ShortVideoDownload,
    caption: str,
    open_label: str,
    open_url: str,
) -> None:
    path = clip.file_path
    size = path.stat().st_size if path.is_file() else 0
    if size > TELEGRAM_USER_VIDEO_MAX_BYTES:
        raise OSError(f"Файл слишком большой для Telegram ({size} байт).")

    buttons = [[Button.url(open_label, open_url)]]
    duration = clip.actual_duration or clip.duration or None
    kwargs: dict = {
        "caption": caption[:1024],
        "parse_mode": "html",
        "supports_streaming": True,
        "video": True,
        "buttons": buttons,
    }
    if duration is not None and duration > 0:
        kwargs["duration"] = int(duration)

    await client.send_file(chat_id, path, **kwargs)
