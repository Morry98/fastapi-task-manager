"""Tests for StatisticsStorage using mocked Redis."""

from unittest.mock import AsyncMock, MagicMock

from fastapi_task_manager.statistics import StatisticsStorage


def _make_mock_redis():
    """Create a mock Redis client with pipeline support.

    Redis.pipeline() is a sync method that returns an async context manager,
    so we use MagicMock for the redis client and configure pipeline accordingly.
    """
    redis = MagicMock()
    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=[])
    # pipeline() is sync but returns an async context manager
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=pipe)
    ctx.__aexit__ = AsyncMock(return_value=False)
    redis.pipeline.return_value = ctx
    # XRANGE is used directly (not via pipeline) for get_statistics
    redis.xrange = AsyncMock(return_value=[])
    return redis, pipe


class TestRecordExecution:
    """Tests for record_execution using Redis Streams."""

    async def test_record_execution_adds_stream_entry(self):
        """Verify XADD is called with correct fields and MAXLEN trimming."""
        redis, pipe = _make_mock_redis()
        storage = StatisticsStorage(redis, max_entries=10, ttl_seconds=300)
        await storage.record_execution("stats_key", 1700000000.0, 2.5)

        # XADD with fields and maxlen
        pipe.xadd.assert_called_once_with(
            "stats_key",
            {"ts": "1700000000.0", "dur": "2.5"},
            maxlen=10,
            approximate=True,
        )
        # TTL refreshed
        pipe.expire.assert_called_once_with("stats_key", 300)
        pipe.execute.assert_awaited_once()

    async def test_record_execution_single_pipeline(self):
        """Verify all operations are batched in a single pipeline."""
        redis, pipe = _make_mock_redis()
        storage = StatisticsStorage(redis, max_entries=30, ttl_seconds=432_000)
        await storage.record_execution("key", 1.0, 0.5)

        # Only one pipeline execution
        pipe.execute.assert_awaited_once()
        # Exactly one XADD and one EXPIRE
        assert pipe.xadd.call_count == 1
        assert pipe.expire.call_count == 1


class TestGetStatistics:
    """Tests for get_statistics (reading from Redis Stream)."""

    async def test_get_statistics_returns_entries(self):
        """Verify stream entries are parsed into dicts with ts and dur."""
        redis, _ = _make_mock_redis()
        redis.xrange = AsyncMock(
            return_value=[
                (b"1700000000000-0", {b"ts": b"100.0", b"dur": b"0.5"}),
                (b"1700000001000-0", {b"ts": b"200.0", b"dur": b"1.0"}),
            ],
        )
        storage = StatisticsStorage(redis, max_entries=500, ttl_seconds=432_000)
        result = await storage.get_statistics("key")

        assert len(result) == 2
        assert result[0] == {"ts": 100.0, "dur": 0.5}
        assert result[1] == {"ts": 200.0, "dur": 1.0}

    async def test_get_statistics_empty_stream(self):
        """Verify empty stream returns empty list."""
        redis, _ = _make_mock_redis()
        redis.xrange = AsyncMock(return_value=[])
        storage = StatisticsStorage(redis, max_entries=500, ttl_seconds=432_000)
        result = await storage.get_statistics("key")
        assert result == []

    async def test_get_statistics_string_keys(self):
        """Verify parsing works when Redis returns string keys (decode_responses=True)."""
        redis, _ = _make_mock_redis()
        redis.xrange = AsyncMock(
            return_value=[
                ("1700000000000-0", {"ts": "42.0", "dur": "3.14"}),
            ],
        )
        storage = StatisticsStorage(redis, max_entries=500, ttl_seconds=432_000)
        result = await storage.get_statistics("key")

        assert len(result) == 1
        assert result[0] == {"ts": 42.0, "dur": 3.14}
