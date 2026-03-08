"""Statistics storage utilities using Redis Lists.

This module provides atomic operations for storing task execution statistics
using Redis Lists. Redis Lists offer:
- Atomic operations (LPUSH, LTRIM)
- Automatic list trimming with LTRIM
- O(1) operations for push and trim
"""

import logging

from redis.asyncio import Redis

logger = logging.getLogger("fastapi.task-manager.statistics")


class StatisticsStorage:
    """Handles storage and retrieval of task execution statistics using Redis Lists.

    This class provides methods for recording execution timestamps and durations
    using Redis Lists for atomic operations. Each statistics list is automatically
    trimmed to keep only the most recent entries.

    Attributes:
        _redis_client: Async Redis client for database operations.
        _max_entries: Maximum number of entries to keep in each list.
        _ttl_seconds: Time-to-live in seconds for statistics keys.
    """

    def __init__(
        self,
        redis_client: Redis,
        max_entries: int = 30,
        ttl_seconds: int = 432_000,  # 5 days
    ) -> None:
        """Initialize the statistics storage.

        Args:
            redis_client: Async Redis client instance.
            max_entries: Maximum number of entries to keep per list.
            ttl_seconds: Expiration time for statistics keys.
        """
        self._redis_client = redis_client
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds

    async def record_run(self, key: str, timestamp: float) -> None:
        """Record a task execution timestamp.

        Adds the timestamp to the beginning of the list and trims to max_entries.
        Uses a pipeline for atomic execution of LPUSH, LTRIM, and EXPIRE.

        Args:
            key: The Redis key for the runs list.
            timestamp: Unix timestamp of the execution.
        """
        async with self._redis_client.pipeline(transaction=True) as pipe:
            # Push new timestamp to the left of the list
            pipe.lpush(key, str(timestamp))
            # Keep only the most recent entries (0 to max_entries-1)
            pipe.ltrim(key, 0, self._max_entries - 1)
            # Set/refresh expiration
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def record_duration(self, key: str, duration_seconds: float) -> None:
        """Record a task execution duration.

        Adds the duration to the beginning of the list and trims to max_entries.
        Uses a pipeline for atomic execution.

        Args:
            key: The Redis key for the durations list.
            duration_seconds: Execution duration in seconds.
        """
        async with self._redis_client.pipeline(transaction=True) as pipe:
            pipe.lpush(key, str(duration_seconds))
            pipe.ltrim(key, 0, self._max_entries - 1)
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def record_execution(
        self,
        runs_key: str,
        durations_key: str,
        timestamp: float,
        duration_seconds: float,
    ) -> None:
        """Record both run timestamp and duration in a single pipeline.

        This is more efficient when recording both statistics at once,
        as it uses a single Redis pipeline for all operations.

        Args:
            runs_key: The Redis key for the runs list.
            durations_key: The Redis key for the durations list.
            timestamp: Unix timestamp of the execution.
            duration_seconds: Execution duration in seconds.
        """
        async with self._redis_client.pipeline(transaction=True) as pipe:
            # Record run timestamp
            pipe.lpush(runs_key, str(timestamp))
            pipe.ltrim(runs_key, 0, self._max_entries - 1)
            pipe.expire(runs_key, self._ttl_seconds)
            # Record duration
            pipe.lpush(durations_key, str(duration_seconds))
            pipe.ltrim(durations_key, 0, self._max_entries - 1)
            pipe.expire(durations_key, self._ttl_seconds)
            await pipe.execute()

    async def get_runs(self, key: str) -> list[float]:
        """Get the list of execution timestamps.

        Args:
            key: The Redis key for the runs list.

        Returns:
            List of Unix timestamps, most recent first.
        """
        values = await self._redis_client.lrange(key, 0, -1)  # ty: ignore[invalid-await]
        return [float(v) for v in values]

    async def get_durations(self, key: str) -> list[float]:
        """Get the list of execution durations.

        Args:
            key: The Redis key for the durations list.

        Returns:
            List of durations in seconds, most recent first.
        """
        values = await self._redis_client.lrange(key, 0, -1)  # ty: ignore[invalid-await]
        return [float(v) for v in values]

    async def get_statistics(
        self,
        runs_key: str,
        durations_key: str,
    ) -> dict[str, list[float]]:
        """Get both runs and durations in a single pipeline.

        Args:
            runs_key: The Redis key for the runs list.
            durations_key: The Redis key for the durations list.

        Returns:
            Dictionary with 'runs' and 'durations' lists.
        """
        async with self._redis_client.pipeline(transaction=True) as pipe:
            pipe.lrange(runs_key, 0, -1)
            pipe.lrange(durations_key, 0, -1)
            results = await pipe.execute()

        return {
            "runs": [float(v) for v in results[0]],
            "durations": [float(v) for v in results[1]],
        }
