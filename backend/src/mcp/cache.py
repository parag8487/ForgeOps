# SPDX-License-Identifier: FSL-1.1-ALv2
"""Redis-authoritative tool-list TTL caching (Design §12.2).

The cache is Redis-authoritative: no local/process-monotonic fallback expiry
state. Redis failure degrades to a cache miss (returns None).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class RedisLike(Protocol):
    """Minimal async Redis interface for testability."""

    async def set(self, name: str, value: str, px: int | None = None) -> Any: ...
    async def get(self, name: str) -> str | None: ...
    async def pttl(self, name: str) -> int: ...


class TtlToolCache:
    """Redis-authoritative tool-list cache with PX-based TTL.

    - Uses Redis SET PX min(server_ttl_ms, max_ttl_ms) for storage.
    - Returns values only when Redis PTTL > 0.
    - Non-positive TTL creates no key.
    - Redis failure degrades to cache miss (returns None).
    - No local/process-monotonic fallback expiry state.
    """

    def __init__(self, redis: RedisLike, *, max_ttl_ms: int = 60_000) -> None:
        self._redis = redis
        self._max_ttl_ms = max_ttl_ms

    async def put(self, key: str, value: str, server_ttl_ms: int) -> bool:
        """Store a value with TTL = min(server_ttl_ms, max_ttl_ms).

        Returns True if the key was stored, False if skipped (non-positive TTL)
        or on Redis failure.
        """
        effective_ttl = min(server_ttl_ms, self._max_ttl_ms)
        if effective_ttl <= 0:
            return False

        try:
            await self._redis.set(key, value, px=effective_ttl)
            return True
        except Exception:
            logger.warning("redis SET failed for key=%s, degrading to miss", key)
            return False

    async def get(self, key: str) -> str | None:
        """Retrieve a value only when Redis PTTL > 0.

        Returns None on cache miss or Redis failure.
        """
        try:
            pttl = await self._redis.pttl(key)
            if pttl <= 0:
                return None
            return await self._redis.get(key)
        except Exception:
            logger.warning("redis GET failed for key=%s, degrading to miss", key)
            return None
