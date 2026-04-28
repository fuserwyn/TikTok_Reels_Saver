from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message, TelegramObject

import asyncpg

from bot.db import upsert_user_visit

logger = logging.getLogger(__name__)


class TrackUsersMiddleware(BaseMiddleware):
    """Фиксирует пользователей лички в PostgreSQL (если pool не None)."""

    def __init__(self, pool: asyncpg.Pool | None) -> None:
        self.pool = pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if self.pool is not None and isinstance(event, Message):
            if event.chat.type == ChatType.PRIVATE and event.from_user:
                u = event.from_user
                try:
                    await upsert_user_visit(self.pool, u.id, u.username)
                except Exception:
                    logger.exception("upsert_user_visit failed for telegram_id=%s", u.id)
        return await handler(event, data)
