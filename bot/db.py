from __future__ import annotations

import logging
import os
import re
import ssl as ssl_module
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


def normalize_database_url(url: str) -> str:
    """asyncpg ожидает ``postgresql://``; Railway иногда отдаёт ``postgres://``."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _ssl_context_no_verify() -> ssl_module.SSLContext:
    """TLS без проверки сертификата (обход self-signed / прокси цепочки)."""

    ctx = ssl_module.create_default_context(ssl_module.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    ctx.verify_mode = ssl_module.CERT_NONE
    return ctx


def _ssl_arg_for_url(url: str) -> Any:
    """``DATABASE_SSL``: false | true | no-verify (или auto)."""

    mode = (os.getenv("DATABASE_SSL") or "").strip().lower()
    if mode in ("0", "false", "no", "off", "disable"):
        return False
    if mode in ("no-verify", "insecure", "relaxed"):
        return _ssl_context_no_verify()
    if mode in ("1", "true", "yes", "require", "on"):
        return True

    if re.search(r"@localhost|@127\.0\.0\.1\b", url, re.I):
        return False

    # auto: без явного DATABASE_SSL — многие хостинги шлют свой CA; verify падает на
    # self-signed in chain → безопаснее для бота к БД в одной сети использовать no-verify
    if not mode and re.search(r"railway\.app|\.internal|render\.com|neon\.tech", url, re.I):
        logger.info("PostgreSQL: авто no-verify SSL (хостинг без публичной цепочки в образе)")
        return _ssl_context_no_verify()

    return True


async def create_pool(database_url: str) -> asyncpg.Pool:
    url = normalize_database_url(database_url)
    ssl = _ssl_arg_for_url(url)
    pool = await asyncpg.create_pool(url, min_size=1, max_size=10, ssl=ssl)
    ssl_log = "false" if ssl is False else ("no-verify" if isinstance(ssl, ssl_module.SSLContext) else "verify")
    logger.info("PostgreSQL pool ready (ssl=%s)", ssl_log)
    return pool


_MIGRATE = """
ALTER TABLE bot_users ADD COLUMN IF NOT EXISTS request_count BIGINT NOT NULL DEFAULT 0;
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    request_count BIGINT NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS bot_users_last_seen_idx ON bot_users (last_seen_at DESC);
"""


async def init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
        await conn.execute(_MIGRATE)
    logger.info("DB schema OK")


async def increment_download_request(
    pool: asyncpg.Pool | None, telegram_id: int, username: str | None
) -> None:
    """+1 к счётчику при попытке скачать по ссылке."""

    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO bot_users (telegram_id, username, request_count, first_seen_at, last_seen_at)
        VALUES ($1, $2, 1, NOW(), NOW())
        ON CONFLICT (telegram_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, bot_users.username),
            request_count = bot_users.request_count + 1,
            last_seen_at = NOW()
        """,
        telegram_id,
        username,
    )


async def fetch_user_stats(pool: asyncpg.Pool) -> tuple[int, int]:
    """Сколько строк (пользователей в таблице); сумма запросов."""

    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)::bigint AS users,
            COALESCE(SUM(request_count), 0)::bigint AS total_requests
        FROM bot_users
        """
    )
    assert row is not None
    return int(row["users"]), int(row["total_requests"])
