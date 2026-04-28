from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .cookies import apply_ytdlp_cookiefile
from .exceptions import SocialVideoError, SocialVideoTooLargeError
from .models import ShortVideoDownload
from .tiktok_expand import TIKTOK_UA, expand_tiktok_short_url
from .urls import normalize_instagram_url

logger = logging.getLogger(__name__)

# Публичный Reels иногда отдаётся стабильнее, чем дефолтный python-requests UA
INSTAGRAM_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


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


def _maybe_faststart_mp4(file_path: Path) -> None:
    """Перемещает ``moov`` в начало (``+faststart``) без перекодирования — часто нужно iOS/Telegram iPhone."""

    if (os.getenv("VIDEO_SKIP_FASTSTART") or "").strip().lower() in ("1", "true", "yes"):
        return
    if file_path.suffix.lower() != ".mp4":
        return
    out = file_path.with_name(file_path.stem + "._fast.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(file_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(out),
            ],
            check=True,
            timeout=900,
        )
        out.replace(file_path)
    except Exception:
        logger.warning("ffmpeg faststart (copy) failed, using original file", exc_info=True)
        if out.exists():
            out.unlink()


def _maybe_transcode_ios_h264(file_path: Path) -> None:
    """Полный перекод в H.264+AAC — тяжело по CPU; включи ``VIDEO_TRANSCODE_IOS=1`` если iPhone всё равно не качает."""

    if (os.getenv("VIDEO_TRANSCODE_IOS") or "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return
    if file_path.suffix.lower() != ".mp4":
        return
    out = file_path.with_name(file_path.stem + "._ios.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(file_path),
                "-c:v",
                "libx264",
                "-profile:v",
                "main",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(out),
            ],
            check=True,
            timeout=1_800,
        )
        out.replace(file_path)
    except Exception:
        logger.warning("ffmpeg iOS transcode failed, using previous file", exc_info=True)
        if out.exists():
            out.unlink()


def _download_merged_mp4_sync(url: str, work_dir: Path) -> ShortVideoDownload:
    if "tiktok.com" in url.lower():
        url = expand_tiktok_short_url(url)
    low = url.lower()
    if "instagram.com" in low or "instagr.am" in low:
        url = normalize_instagram_url(url)

    out_template = str(work_dir / "%(title).200B.%(ext)s")
    opts: dict[str, Any] = {
        "format": (
            "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec^=avc][ext=mp4]+bestaudio[ext=m4a]/"
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
    low = url.lower()
    if "tiktok.com" in low:
        opts["http_headers"] = {"User-Agent": TIKTOK_UA}
    elif "instagram.com" in low or "instagr.am" in low:
        opts["http_headers"] = INSTAGRAM_HTTP_HEADERS

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

    # iOS/Telegram часто не играют файл без faststart (moov в конце) или с HEVC — см. ниже
    if file_path.suffix.lower() == ".mp4":
        ios_tc = (os.getenv("VIDEO_TRANSCODE_IOS") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if ios_tc:
            _maybe_transcode_ios_h264(file_path)
        else:
            _maybe_faststart_mp4(file_path)

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
    """Скачать один публичный TikTok / Reels (и то, что yt-dlp тянет тем же пайплайном).

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
