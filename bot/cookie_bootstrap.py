from __future__ import annotations

import base64
import binascii
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Короткоживущие Google/YouTube cookie: браузер их постоянно ротирует, поэтому в выгрузке
# они почти всегда уже протухли. Со свежим __Secure-1PSID стабильная сессия работает, а вот
# протухший __Secure-1PSIDTS ломает ответ YouTube (форматы не отдаются). Вырезаем их —
# это рекомендованный воркэраунд yt-dlp. Отключается через COOKIES_KEEP_ROTATION=1.
_VOLATILE_COOKIE_NAMES = frozenset(
    {
        "__Secure-1PSIDTS",
        "__Secure-3PSIDTS",
        "SIDCC",
        "__Secure-1PSIDCC",
        "__Secure-3PSIDCC",
    }
)


def _sanitize_cookie_text(text: str) -> str:
    """Убрать протухающие ротационные Google-cookie из Netscape cookies.txt."""

    if (os.getenv("COOKIES_KEEP_ROTATION") or "").strip().lower() in ("1", "true", "yes", "on"):
        return text
    kept: list[str] = []
    dropped = 0
    for line in text.splitlines():
        if line and not line.startswith("#"):
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] in _VOLATILE_COOKIE_NAMES:
                dropped += 1
                continue
        kept.append(line)
    if dropped:
        logger.info("cookies: убрано %s ротационных Google-cookie (см. COOKIES_KEEP_ROTATION)", dropped)
    out = "\n".join(kept)
    if not out.endswith("\n"):
        out += "\n"
    return out


def _cookie_target_path() -> Path:
    """Куда писать cookies.txt.

    Если задан ``YT_DLP_COOKIEFILE`` — пишем туда (например, в volume ``/data/cookies.txt``).
    Иначе кладём во временный каталог ОС — тогда на Railway достаточно одной переменной
    ``COOKIES_TXT_B64`` и никакого volume не нужно.
    """

    raw = (os.getenv("YT_DLP_COOKIEFILE") or "").strip()
    # Railway/секреты иногда сохраняют значение в кавычках — снимаем.
    if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
        raw = raw[1:-1].strip()
    if raw:
        return Path(raw).expanduser()
    return Path(tempfile.gettempdir()) / "ytdlp_cookies.txt"


def bootstrap_cookies_file_from_env() -> Path | None:
    """Без интерактивного shell: записать Netscape cookies из переменных окружения в файл.

    Задай в Railway (Secret) одно из:
    - ``COOKIES_TXT_B64`` — содержимое ``cookies.txt`` в Base64 (одна строка);
    - ``COOKIES_TXT`` — сырое тело файла (если платформа отдаёт многострочный секрет).

    Путь файла — ``YT_DLP_COOKIEFILE`` (если задан) или временный файл ОС. После записи
    переменная ``YT_DLP_COOKIEFILE`` проставляется на этот путь, чтобы yt-dlp её подхватил.
    Возвращает путь к файлу или ``None``, если cookies в окружении нет / записать не удалось.
    """

    b64 = (os.getenv("COOKIES_TXT_B64") or "").strip()
    raw_env = os.getenv("COOKIES_TXT") or ""
    if not b64 and not raw_env.strip():
        return None

    path = _cookie_target_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("cookies bootstrap: cannot mkdir %s: %s", path.parent, exc)
        return None

    if b64:
        # Секрет мог прийти с переносами строк/пробелами — база64 их не терпит.
        b64_clean = "".join(b64.split())
        try:
            data = base64.standard_b64decode(b64_clean)
        except (binascii.Error, ValueError) as exc:
            logger.error("COOKIES_TXT_B64: invalid base64 (%s)", exc)
            return None
        source = "COOKIES_TXT_B64"
        text = data.decode("utf-8", errors="replace")
    else:
        source = "COOKIES_TXT"
        text = raw_env

    text = _sanitize_cookie_text(text)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        logger.warning("cookies bootstrap: cannot write %s: %s", path, exc)
        return None
    logger.info("Cookies file written from %s → %s (%s bytes).", source, path, len(text.encode("utf-8")))

    # Чтобы core.cookies.apply_ytdlp_cookiefile нашёл файл даже без явного YT_DLP_COOKIEFILE.
    os.environ["YT_DLP_COOKIEFILE"] = str(path.resolve())
    return path
