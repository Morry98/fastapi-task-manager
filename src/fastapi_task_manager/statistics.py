"""Statistics storage utilities using Redis Streams.

This module provides atomic operations for storing task execution statistics
using Redis Streams. Redis Streams offer:
- Atomic XADD with automatic MAXLEN trimming
- Structured entries with multiple fields (timestamp + duration correlated)
- Time-ordered IDs for natural chronological ordering
- Extensible: new fields can be added without breaking existing data
"""

import logging

from redis.asyncio import Redis

logger = logging.getLogger("fastapi.task-manager.statistics")


class StatisticsStorage:
    """Handles storage and retrieval of task execution statistics using Redis Streams.

    Each execution is recorded as a single stream entry containing both the
    timestamp and duration, ensuring they are always correlated. The stream
    is automatically trimmed to keep only the most recent entries.

    Attributes:
        _redis_client: Async Redis client for database operations.
        _max_entries: Maximum number of entries to keep in the stream.
        _ttl_seconds: Time-to-live in seconds for statistics keys.
    """

    def __init__(
        self,
        redis_client: Redis,
        max_entries: int,
        ttl_seconds: int,
    ) -> None:
        """Initialize the statistics storage.

        Args:
            redis_client: Async Redis client instance.
            max_entries: Maximum number of entries to keep per stream.
            ttl_seconds: Expiration time for statistics keys.
        """
        self._redis_client = redis_client
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds

    async def record_execution(
        self,
        stream_key: str,
        timestamp: float,
        duration_seconds: float,
    ) -> None:
        """Record a task execution (timestamp + duration) as a single stream entry.

        Uses XADD with approximate MAXLEN trimming to keep the stream bounded,
        followed by EXPIRE to set the TTL. Both commands are sent in a pipeline.

        Args:
            stream_key: The Redis key for the statistics stream.
            timestamp: Unix timestamp of the execution.
            duration_seconds: Execution duration in seconds.
        """
        async with self._redis_client.pipeline(transaction=True) as pipe:
            # Add entry with both fields; approximate MAXLEN trim is O(1) amortized
            pipe.xadd(
                stream_key,
                {"ts": str(timestamp), "dur": str(duration_seconds)},
                maxlen=self._max_entries,
                approximate=True,
            )
            # Refresh TTL on every write
            pipe.expire(stream_key, self._ttl_seconds)
            await pipe.execute()

    async def get_statistics(
        self,
        stream_key: str,
    ) -> list[dict[str, float]]:
        """Get execution history from the statistics stream.

        Returns entries in chronological order (oldest first), each containing
        'ts' (Unix timestamp) and 'dur' (duration in seconds).

        Args:
            stream_key: The Redis key for the statistics stream.

        Returns:
            List of dicts with 'ts' and 'dur' float values, oldest first.
        """
        # XRANGE returns entries in chronological order (oldest → newest)
        entries = await self._redis_client.xrange(stream_key)  # ty: ignore[invalid-await]

        return [
            {
                "ts": float(fields.get(b"ts", fields.get("ts", 0))),
                "dur": float(fields.get(b"dur", fields.get("dur", 0))),
            }
            for _entry_id, fields in entries
        ]
