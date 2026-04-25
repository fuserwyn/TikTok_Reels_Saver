from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def load_settings() -> tuple[str, Path, int]:
    token = (os.getenv("TELEGRAM_API_KEY") or os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "Задай TELEGRAM_API_KEY или BOT_TOKEN в переменных окружения (Railway Variables)."
        )
    download_dir = Path(os.getenv("DOWNLOAD_DIR", "/tmp/social_fetch"))
    download_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
    return token, download_dir, max_bytes
