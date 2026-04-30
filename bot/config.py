from __future__ import annotations

import os
from typing import FrozenSet

from dotenv import load_dotenv

load_dotenv()


def load_settings() -> tuple[str, int]:
    token = (os.getenv("TELEGRAM_API_KEY") or os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "Задай TELEGRAM_API_KEY или BOT_TOKEN в переменных окружения (Railway Variables)."
        )
    max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
    return token, max_bytes


def load_database_url() -> str | None:
    """PostgreSQL (Railway подставляет DATABASE_URL при подключении плагина)."""
    return (os.getenv("DATABASE_URL") or "").strip() or None


def load_stats_admin_ids() -> FrozenSet[int]:
    raw = (os.getenv("STATS_ADMIN_IDS") or "").strip()
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return frozenset(ids)


def load_ytdlp_autoupdate_hours() -> float:
    """Интервал автообновления yt-dlp в часах (0 = выключено)."""
    raw = (os.getenv("YT_DLP_AUTOUPDATE_HOURS") or "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if value > 0 else 0.0
