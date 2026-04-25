from __future__ import annotations

import logging
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
        try:
            if self.file_path.exists():
                self.file_path.unlink()
        except OSError:
            logger.warning("Failed to remove %s", self.file_path, exc_info=True)
        parent = self.file_path.parent
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
