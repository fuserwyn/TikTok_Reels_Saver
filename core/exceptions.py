from __future__ import annotations


class SocialVideoError(Exception):
    """yt-dlp / сеть / разбор страницы для TikTok и Reels."""


class SocialVideoTooLargeError(SocialVideoError):
    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"File is {size_bytes / 1024 / 1024:.1f} MB, exceeds limit "
            f"{limit_bytes / 1024 / 1024:.0f} MB."
        )
