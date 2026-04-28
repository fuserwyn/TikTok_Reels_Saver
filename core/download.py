from __future__ import annotations

import asyncio
import json
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


def _probe_video_display_size(path: Path) -> tuple[int | None, int | None]:
    """Ширина/высота для UI (с учётом тега rotate, как на телефонах). Для sendVideo / iOS."""

    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        data = json.loads(out.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None, None
        st = streams[0]
        w = int(st["width"])
        h = int(st["height"])
        rot = 0
        for sd in st.get("side_data_list") or []:
            r = sd.get("rotation")
            if r is not None:
                rot = int(r)
                break
        else:
            tags = st.get("tags") or {}
            tr = tags.get("rotate")
            if tr is not None:
                try:
                    rot = int(str(tr).strip())
                except ValueError:
                    rot = 0
        # Ориентация показа: если поворот на 90°, в размерах строки местами
        rn = rot % 360
        if rn < 0:
            rn += 360
        if rn in (90, 270):
            w, h = h, w
        return (w, h)
    except Exception:
        logger.warning("ffprobe width/height failed for %s", path, exc_info=True)
        return (None, None)


def _merge_instagram_extractor_opts(opts: dict[str, Any]) -> None:
    """Опционально INSTAGRAM_APP_ID — другой X-IG-App-ID (см. wiki yt-dlp instagram)."""

    raw = (os.getenv("INSTAGRAM_APP_ID") or "").strip()
    if not raw:
        return
    ex = dict(opts.get("extractor_args") or {})
    ig = dict(ex.get("instagram") or {})
    ig["app_id"] = raw
    ex["instagram"] = ig
    opts["extractor_args"] = ex
    logger.info("instagram extractor app_id from INSTAGRAM_APP_ID")


# Не подменяем http_headers для Instagram — у yt-dlp свои заголовки API (X-IG-App-ID и т.д.);
# подмена «браузерным» UA ломала скачивание с Railway без cookies.


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


def _video_lightweight_only() -> bool:
    """Только remux faststart без перекода — меньше CPU, хуже совместимость с iPhone."""

    if (os.getenv("VIDEO_LIGHTWEIGHT") or "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    # совместимость со старым VIDEO_TRANSCODE_IOS=0 (= не перекодировать)
    return (os.getenv("VIDEO_TRANSCODE_IOS") or "").strip().lower() in ("0", "false", "no")


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


def _ffmpeg_ios_encode_cmd(src: Path, dst: Path) -> list[str]:
    """Один пайплайн для MP4 после yt-dlp и для webm/mkv → mp4."""

    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+genpts",
        "-i",
        str(src),
        "-vf",
        # Явные квадратные пиксели; размеры для клиента — ffprobe + width/height в sendVideo (важно для iOS)
        r"scale=-2:-2:flags=bilinear,format=yuv420p,setsar=1",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "-avoid_negative_ts",
        "make_zero",
        str(dst),
    ]


def _transcode_in_place_for_ios_h264(file_path: Path) -> None:
    """Перекод в H.264+AAC — по умолчанию вкл.; для экономии CPU см. VIDEO_LIGHTWEIGHT."""

    if file_path.suffix.lower() != ".mp4":
        return
    out = file_path.with_name(file_path.stem + "._ios.mp4")
    try:
        subprocess.run(_ffmpeg_ios_encode_cmd(file_path, out), check=True, timeout=3_600)
        out.replace(file_path)
        logger.info("ios transcode ok: %s", file_path.name)
    except Exception:
        logger.warning("ffmpeg iOS transcode failed, keeping file as-is", exc_info=True)
        if out.exists():
            out.unlink()


def _convert_to_ios_mp4_replace(src: Path) -> Path:
    """webm/mkv → один mp4 под iOS; при ошибке возвращаем src."""

    ext = src.suffix.lower()
    if ext not in (".webm", ".mkv"):
        return src
    dst = src.with_suffix(".mp4")
    tmp = src.with_name(src.stem + "._conv.mp4")
    try:
        subprocess.run(_ffmpeg_ios_encode_cmd(src, tmp), check=True, timeout=3_600)
        src.unlink(missing_ok=True)
        tmp.replace(dst)
        logger.info("container→mp4 ios: %s", dst.name)
        return dst
    except Exception:
        logger.warning("ffmpeg webm/mkv→mp4 failed", exc_info=True)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return src


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
        _merge_instagram_extractor_opts(opts)

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

    # iPhone: «картинка на паузе, звук идёт» — типично HEVC/VFR/сломанные метки времени; нужен перекод H.264 CFR.
    # По умолчанию полный перекод для mp4; VIDEO_LIGHTWEIGHT=1 — только faststart (-c copy), дешевле CPU, хуже для iOS.
    # webm/mkv на iOS почти не играют — всегда конвертируем в mp4 тем же пайплайном.
    ext = file_path.suffix.lower()
    if ext in (".webm", ".mkv"):
        file_path = _convert_to_ios_mp4_replace(file_path)
    elif ext == ".mp4":
        if _video_lightweight_only():
            _maybe_faststart_mp4(file_path)
        else:
            _transcode_in_place_for_ios_h264(file_path)

    title = str(info.get("title") or file_path.stem)
    claimed = int(info.get("duration") or 0)
    actual = _read_video_duration(file_path) or claimed
    if actual <= 0 and file_path.suffix.lower() == ".webm":
        actual = claimed

    vw, vh = _probe_video_display_size(file_path)

    return ShortVideoDownload(
        file_path=file_path,
        title=title[:200],
        artist=_extract_uploader(info) or "—",
        duration=claimed,
        actual_duration=actual,
        thumbnail_url=info.get("thumbnail"),
        webpage_url=str(info.get("webpage_url") or url),
        width=vw,
        height=vh,
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
