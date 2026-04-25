from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .cookies import apply_ytdlp_cookiefile
from .exceptions import SocialVideoError, SocialVideoTooLargeError
from .models import ShortVideoDownload
from .tiktok_expand import TIKTOK_UA, expand_tiktok_short_url

logger = logging.getLogger(__name__)


def _extract_uploader(info: dict[str, Any]) -> str:
    for key in ("artist", "uploader", "channel", "creator"):
        value = info.get(key)
        if value:
            return str(value)
    return ""


def _read_video_duration(file_path: Path) -> int:
    try:
        from mutagen.mp4 import MP4

        return int(MP4(file_path).info.length)
    except Exception:
        return 0


def _download_merged_mp4_sync(url: str, work_dir: Path) -> ShortVideoDownload:
    if "tiktok.com" in url.lower():
        url = expand_tiktok_short_url(url)

    out_template = str(work_dir / "%(title).200B.%(ext)s")
    opts: dict[str, Any] = {
        "format": (
            "bestvideo[ext=mp4][vcodec!=none]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec!=none]+bestaudio/best[vcodec!=none]/best"
        ),
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
    }
    apply_ytdlp_cookiefile(opts)
    if "tiktok.com" in url.lower():
        opts["http_headers"] = {"User-Agent": TIKTOK_UA}

    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except DownloadError as exc:
            raise SocialVideoError(f"yt-dlp failed: {exc}") from exc

    if not info:
        raise SocialVideoError("yt-dlp returned no info for this URL.")

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise SocialVideoError("Список пуст.")
        info = entries[0]

    requested = info.get("requested_downloads") or []
    file_path: Path | None = None
    if requested:
        file_path = Path(requested[0].get("filepath") or requested[0].get("_filename"))
    if file_path is None or not file_path.exists():
        candidate = info.get("filepath") or info.get("_filename")
        file_path = Path(candidate) if candidate else None
    if file_path is None or not file_path.exists():
        mp4s = sorted(work_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4s:
            file_path = mp4s[0]
    if file_path is None or not file_path.exists():
        webms = sorted(work_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if webms:
            file_path = webms[0]
    if file_path is None or not file_path.exists():
        raise SocialVideoError("Скачанный файл не найден на диске.")

    title = str(info.get("title") or file_path.stem)
    claimed = int(info.get("duration") or 0)
    actual = _read_video_duration(file_path) or claimed
    if actual <= 0 and file_path.suffix.lower() == ".webm":
        actual = claimed

    return ShortVideoDownload(
        file_path=file_path,
        title=title[:200],
        artist=_extract_uploader(info) or "—",
        duration=claimed,
        actual_duration=actual,
        thumbnail_url=info.get("thumbnail"),
        webpage_url=str(info.get("webpage_url") or url),
    )


async def download_social_video(
    url: str,
    max_bytes: int,
) -> ShortVideoDownload:
    """Скачать один публичный TikTok / Reels / YouTube Shorts (и то, что yt-dlp тянет тем же пайплайном).

    Файл пишется во временный каталог ОС (как требует yt-dlp); после отправки в Telegram
    вызывай ``ShortVideoDownload.cleanup()`` — на сервере ничего не копим.
    """

    work_dir = Path(tempfile.mkdtemp(prefix="svf_"))

    try:
        clip = await asyncio.to_thread(_download_merged_mp4_sync, url, work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    size = clip.file_path.stat().st_size
    if size > max_bytes:
        clip.cleanup()
        raise SocialVideoTooLargeError(size, max_bytes)

    return clip
