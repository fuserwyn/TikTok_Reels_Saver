from __future__ import annotations

import os
from typing import FrozenSet

from dotenv import load_dotenv

load_dotenv()

# Лимит sendVideo у Telegram Bot API (≈50 МБ).
TELEGRAM_BOT_VIDEO_MAX_BYTES = 50 * 1024 * 1024


def load_mtproto_app_credentials() -> tuple[int, str] | None:
    """API_ID + API_HASH с my.telegram.org — нужны для Pyrogram (бот и при необходимости user session)."""

    raw_id = (os.getenv("API_ID") or os.getenv("TELEGRAM_API_ID") or "").strip()
    api_hash = (os.getenv("API_HASH") or os.getenv("TELEGRAM_API_HASH") or "").strip()
    if not raw_id or not api_hash:
        return None
    try:
        return int(raw_id), api_hash
    except ValueError:
        return None


def load_user_session_string() -> str | None:
    """Строка сессии Pyrogram (не формат Telethon)."""

    s = (os.getenv("TELEGRAM_SESSION") or "").strip()
    return s or None


def load_settings() -> tuple[str, int, bool]:
    """Токен, лимит скачивания (байты), флаг «MAX_UPLOAD_BYTES задан в .env явно»."""

    token = (os.getenv("TELEGRAM_API_KEY") or os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "Задай TELEGRAM_API_KEY или BOT_TOKEN в переменных окружения (Railway Variables)."
        )
    raw = os.getenv("MAX_UPLOAD_BYTES")
    if raw is None or not str(raw).strip():
        return token, TELEGRAM_BOT_VIDEO_MAX_BYTES, False
    return token, int(str(raw).strip()), True


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
