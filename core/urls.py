from __future__ import annotations

import re

INSTAGRAM_REEL_RE = re.compile(
    r"https?://(?:www\.)?(?:instagram\.com|instagr\.am)/(?:reel|reels|share/reel)/[A-Za-z0-9_-]+[^\s]*",
    re.IGNORECASE,
)

TIKTOK_URL_RE = re.compile(
    r"https?://(?:(?:www|m|vm|vt|lc)\.)?tiktok\.com/[^\s]+",
    re.IGNORECASE,
)

# Только /shorts/ — не ловим обычные длинные ролики youtu.be / watch
YOUTUBE_SHORTS_RE = re.compile(
    r"https?://(?:(?:www|m)\.)?youtube\.com/shorts/[A-Za-z0-9_-]+[^\s]*",
    re.IGNORECASE,
)


def strip_trailing_junk(url: str) -> str:
    while url and url[-1] in ").,];\"'":
        url = url[:-1]
    return url


def find_instagram_reel_url(text: str) -> str | None:
    match = INSTAGRAM_REEL_RE.search(text or "")
    return strip_trailing_junk(match.group(0)) if match else None


def find_tiktok_url(text: str) -> str | None:
    match = TIKTOK_URL_RE.search(text or "")
    return strip_trailing_junk(match.group(0)) if match else None


def find_youtube_shorts_url(text: str) -> str | None:
    match = YOUTUBE_SHORTS_RE.search(text or "")
    return strip_trailing_junk(match.group(0)) if match else None
