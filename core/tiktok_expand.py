from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

TIKTOK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def tiktok_url_needs_expand(url: str) -> bool:
    u = url.lower()
    if "vm.tiktok.com" in u or "vt.tiktok.com" in u:
        return True
    if re.search(r"https?://(?:www\.)?tiktok\.com/t/[A-Za-z0-9]", u):
        return True
    return False


def canonical_from_tiktok_html(html: str) -> str | None:
    for pattern in (
        r'property="og:url"\s+content="(https://www\.tiktok\.com/[^"]+)"',
        r'<link[^>]+rel="canonical"[^>]+href="(https://www\.tiktok\.com/[^"]+)"',
        r'"canonicalUrl"\s*:\s*"(https:\\/\\/www\.tiktok\.com[^"]+)"',
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            cand = m.group(1).replace("\\/", "/")
            if "/@" in cand and "/video/" in cand:
                return cand.split("?")[0].rstrip("/")
    return None


def expand_tiktok_short_url(url: str, timeout: float = 22.0) -> str:
    """Развернуть vm/vt/t/ в www.tiktok.com/@user/video/id при возможности."""

    if not tiktok_url_needs_expand(url):
        return url

    headers = {
        "User-Agent": TIKTOK_UA,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                final = resp.geturl()
                if final != url and "tiktok.com" in final.lower():
                    if "/@" in final and "/video/" in final:
                        logger.info("TikTok URL expanded (%s): %s -> %s", method, url, final)
                        return final.split("?")[0].rstrip("/")
                    if "vm.tiktok.com" not in final.lower() and "vt.tiktok.com" not in final.lower():
                        logger.info("TikTok URL expanded (%s): %s -> %s", method, url, final)
                        return final.split("?")[0].rstrip("/")
                if method == "GET":
                    chunk = resp.read(700_000)
                    text = chunk.decode("utf-8", errors="ignore")
                    canon = canonical_from_tiktok_html(text)
                    if canon:
                        logger.info("TikTok URL expanded (HTML): %s -> %s", url, canon)
                        return canon
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 501):
                logger.debug("TikTok expand %s %s: HTTP %s", method, url, exc.code)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.debug("TikTok expand %s %s: %s", method, url, exc)

    return url
