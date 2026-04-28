from __future__ import annotations

import logging
import os
import re
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


def normalize_database_url(url: str) -> str:
    """asyncpg ожидает ``postgresql://``; Railway иногда отдаёт ``postgres://``."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _ssl_arg_for_url(url: str) -> Any:
    """Локальный Postgres без TLS; облако — с TLS."""
    explicit = (os.getenv("DATABASE_SSL") or "").strip().lower()
    if explicit in ("0", "false", "no"):
        return False
    if explicit in ("1", "true", "yes"):
        return True
    if re.search(r"@localhost|@127\.0\.0\.1", url, re.I):
        return False
    return True


async def create_pool(database_url: str) -> asyncpg.Pool:
    url = normalize_database_url(database_url)
    ssl = _ssl_arg_for_url(url)
    pool = await asyncpg.create_pool(url, min_size=1, max_size=10, ssl=ssl)
    logger.info("PostgreSQL pool ready (ssl=%s)", ssl)
    return pool


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS bot_users_last_seen_idx ON bot_users (last_seen_at DESC);
"""


async def init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
    logger.info("DB schema OK")


async def upsert_user_visit(pool: asyncpg.Pool, telegram_id: int, username: str | None) -> None:
    await pool.execute(
        """
        INSERT INTO bot_users (telegram_id, username, first_seen_at, last_seen_at)
        VALUES ($1, $2, NOW(), NOW())
        ON CONFLICT (telegram_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, bot_users.username),
            last_seen_at = NOW()
        """,
        telegram_id,
        username,
    )


async def fetch_user_stats(pool: asyncpg.Pool) -> tuple[int, int]:
    """Всего пользователей; впервые за сегодня (с начала дня UTC)."""
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)::bigint AS total,
            COUNT(*) FILTER (
                WHERE first_seen_at >= date_trunc('day', timezone('utc', now()))
            )::bigint AS new_today_utc
        FROM bot_users
        """
    )
    assert row is not None
    return int(row["total"]), int(row["new_today_utc"])
