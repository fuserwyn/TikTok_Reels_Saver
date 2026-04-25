from __future__ import annotations

import os

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
