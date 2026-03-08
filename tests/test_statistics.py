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
    # Keep lrange as async (used directly, not via pipeline)
    redis.lrange = AsyncMock(return_value=[])
    return redis, pipe


class TestRecordRun:
    """Tests for record_run."""

    async def test_record_run_pushes_and_trims(self):
        redis, pipe = _make_mock_redis()
        storage = StatisticsStorage(redis, max_entries=10, ttl_seconds=300)
        await storage.record_run("runs_key", 1700000000.0)

        pipe.lpush.assert_called_once_with("runs_key", "1700000000.0")
        pipe.ltrim.assert_called_once_with("runs_key", 0, 9)
        pipe.expire.assert_called_once_with("runs_key", 300)
        pipe.execute.assert_awaited_once()


class TestRecordDuration:
    """Tests for record_duration."""

    async def test_record_duration_pushes_and_trims(self):
        redis, pipe = _make_mock_redis()
        storage = StatisticsStorage(redis, max_entries=5, ttl_seconds=600)
        await storage.record_duration("dur_key", 1.234)

        pipe.lpush.assert_called_once_with("dur_key", "1.234")
        pipe.ltrim.assert_called_once_with("dur_key", 0, 4)
        pipe.expire.assert_called_once_with("dur_key", 600)


class TestRecordExecution:
    """Tests for record_execution (combined run + duration)."""

    async def test_record_execution_writes_both_in_single_pipeline(self):
        redis, pipe = _make_mock_redis()
        storage = StatisticsStorage(redis, max_entries=3, ttl_seconds=100)
        await storage.record_execution("rk", "dk", 1700000000.0, 2.5)

        # Should have two lpush, two ltrim, two expire calls
        assert pipe.lpush.call_count == 2
        assert pipe.ltrim.call_count == 2
        assert pipe.expire.call_count == 2
        pipe.execute.assert_awaited_once()


class TestGetRuns:
    """Tests for get_runs."""

    async def test_get_runs_converts_to_floats(self):
        redis, _ = _make_mock_redis()
        redis.lrange = AsyncMock(return_value=[b"1.0", b"2.0", b"3.0"])
        storage = StatisticsStorage(redis)
        result = await storage.get_runs("key")
        assert result == [1.0, 2.0, 3.0]

    async def test_get_runs_empty_list(self):
        redis, _ = _make_mock_redis()
        redis.lrange = AsyncMock(return_value=[])
        storage = StatisticsStorage(redis)
        result = await storage.get_runs("key")
        assert result == []


class TestGetDurations:
    """Tests for get_durations."""

    async def test_get_durations_converts_to_floats(self):
        redis, _ = _make_mock_redis()
        redis.lrange = AsyncMock(return_value=[b"0.5", b"1.5"])
        storage = StatisticsStorage(redis)
        result = await storage.get_durations("key")
        assert result == [0.5, 1.5]


class TestGetStatistics:
    """Tests for get_statistics (combined read)."""

    async def test_get_statistics_returns_both_lists(self):
        redis, pipe = _make_mock_redis()
        pipe.execute = AsyncMock(return_value=[[b"100.0", b"200.0"], [b"0.5", b"1.0"]])

        storage = StatisticsStorage(redis)
        result = await storage.get_statistics("rk", "dk")

        assert result["runs"] == [100.0, 200.0]
        assert result["durations"] == [0.5, 1.0]
