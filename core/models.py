from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ShortVideoDownload:
    """Результат скачивания одного короткого ролика (TikTok / Reels)."""

    file_path: Path
    title: str
    artist: str
    duration: int
    actual_duration: int
    thumbnail_url: str | None
    webpage_url: str

    def cleanup(self) -> None:
        """Удаляет весь рабочий каталог скачивания (мусор от yt-dlp, не только mp4)."""
        try:
            shutil.rmtree(self.file_path.parent, ignore_errors=True)
        except OSError:
            logger.warning("Failed to remove %s", self.file_path.parent, exc_info=True)
