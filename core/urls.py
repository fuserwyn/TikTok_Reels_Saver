from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

INSTAGRAM_REEL_RE = re.compile(
    r"https?://(?:www\.)?(?:instagram\.com|instagr\.am)/(?:reel|reels|share/reel)/[A-Za-z0-9_-]+[^\s]*",
    re.IGNORECASE,
)

TIKTOK_URL_RE = re.compile(
    r"https?://(?:(?:www|m|vm|vt|lc)\.)?tiktok\.com/[^\s]+",
    re.IGNORECASE,
)


def strip_trailing_junk(url: str) -> str:
    while url and url[-1] in ").,];\"'":
        url = url[:-1]
    return url


def normalize_instagram_url(url: str) -> str:
    """Убирает ?igsh= и прочий query — иногда мешает yt-dlp."""

    raw = strip_trailing_junk(url.strip())
    try:
        p = urlparse(raw)
        host = (p.netloc or "").lower()
        if "instagram.com" not in host and "instagr.am" not in host:
            return raw
        pl = (p.path or "").lower()
        if "/reel" in pl or "/share/reel" in pl:
            return urlunparse((p.scheme or "https", p.netloc, p.path.rstrip("/") + "/", "", "", ""))
        return raw
    except Exception:
        return raw


def find_instagram_reel_url(text: str) -> str | None:
    match = INSTAGRAM_REEL_RE.search(text or "")
    if not match:
        return None
    return normalize_instagram_url(match.group(0))


def find_tiktok_url(text: str) -> str | None:
    match = TIKTOK_URL_RE.search(text or "")
    return strip_trailing_junk(match.group(0)) if match else None
