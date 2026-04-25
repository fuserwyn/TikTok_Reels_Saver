from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def apply_ytdlp_cookiefile(opts: dict[str, Any]) -> None:
    """Подставить Netscape ``cookies.txt`` (один файл может содержать куки YouTube, TikTok, Reels)."""

    for key in (
        "YT_DLP_COOKIEFILE",
        "YOUTUBE_COOKIEFILE",
        "TIKTOK_COOKIEFILE",
        "INSTAGRAM_COOKIEFILE",
    ):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if path.is_file():
            opts["cookiefile"] = str(path.resolve())
            logger.info("yt-dlp using cookies from %s (%s)", path, key)
            return
        logger.warning("%s=%s is not a readable file, yt-dlp cookies skipped.", key, raw)
