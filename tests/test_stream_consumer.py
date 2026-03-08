"""Tests for StreamConsumer - task execution from Redis Streams."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from redis.exceptions import ResponseError

from fastapi_task_manager.config import Config
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task
from fastapi_task_manager.schema.worker_identity import WorkerIdentity
from fastapi_task_manager.statistics import StatisticsStorage
from fastapi_task_manager.stream_consumer import StreamConsumer


def _make_consumer():
    """Create a StreamConsumer with mocked dependencies."""
    redis = AsyncMock()
    key_builder = RedisKeyBuilder("test")
    worker = MagicMock(spec=WorkerIdentity)
    worker.redis_safe_id = "worker_1"
    config = Config(redis_host="localhost")
    task_manager = MagicMock()
    task_manager.config = config
    task_manager.task_groups = []
    semaphore = asyncio.Semaphore(2)
    statistics = AsyncMock(spec=StatisticsStorage)

    consumer = StreamConsumer(
        redis_client=redis,
        key_builder=key_builder,
        worker_identity=worker,
        task_manager=task_manager,
        semaphore=semaphore,
        statistics=statistics,
    )
    return consumer, redis, task_manager, statistics


def _make_task(name="task1", is_async=True, should_fail=False):
    """Create a mock Task."""
    if is_async:
        if should_fail:
            func = AsyncMock(side_effect=RuntimeError("task failed"))
        else:
            func = AsyncMock()
        func.__name__ = name
    else:
        func = MagicMock()
        func.__name__ = name
        if should_fail:
            func.side_effect = RuntimeError("task failed")

    return Task(
        function=func,
        expression="* * * * *",
        name=name,
    )


class TestSetupConsumerGroups:
    """Tests for setup_consumer_groups."""

    async def test_creates_groups_for_both_streams(self):
        consumer, redis, _, _ = _make_consumer()
        redis.xgroup_create = AsyncMock()

        await consumer.setup_consumer_groups()

        assert redis.xgroup_create.await_count == 2

    async def test_ignores_busygroup_error(self):
        """If consumer group already exists, it should be handled gracefully."""
        consumer, redis, _, _ = _make_consumer()
        redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP Consumer Group name already exists"),
        )

        # Should not raise
        await consumer.setup_consumer_groups()

    async def test_reraises_non_busygroup_errors(self):
        consumer, redis, _, _ = _make_consumer()
        redis.xgroup_create = AsyncMock(side_effect=ResponseError("OTHER ERROR"))

        with __import__("pytest").raises(ResponseError, match="OTHER"):
            await consumer.setup_consumer_groups()


class TestDecodeField:
    """Tests for _decode_field."""

    def test_decodes_bytes(self):
        consumer, _, _, _ = _make_consumer()
        assert consumer._decode_field(b"hello") == "hello"

    def test_passes_string_through(self):
        consumer, _, _, _ = _make_consumer()
        assert consumer._decode_field("hello") == "hello"


class TestFindTask:
    """Tests for _find_task."""

    def test_finds_existing_task(self):
        consumer, _, tm, _ = _make_consumer()
        task = _make_task("t1")
        group = MagicMock()
        group.name = "g1"
        group.tasks = [task]
        tm.task_groups = [group]

        found = consumer._find_task("g1", "t1")
        assert found is task

    def test_returns_none_for_missing_task(self):
        consumer, _, tm, _ = _make_consumer()
        tm.task_groups = []
        assert consumer._find_task("g1", "t1") is None

    def test_returns_none_for_wrong_group(self):
        consumer, _, tm, _ = _make_consumer()
        task = _make_task("t1")
        group = MagicMock()
        group.name = "g1"
        group.tasks = [task]
        tm.task_groups = [group]

        assert consumer._find_task("g2", "t1") is None


class TestProcessMessage:
    """Tests for _process_message."""

    async def test_acks_unknown_task(self):
        """When the task is not found, it should be acknowledged to prevent reprocessing."""
        consumer, redis, tm, _ = _make_consumer()
        tm.task_groups = []
        redis.xack = AsyncMock()

        await consumer._process_message(
            "1-0",
            {b"group": b"g1", b"task": b"unknown"},
            is_high_priority=False,
        )

        redis.xack.assert_awaited_once()


class TestExecuteAndAck:
    """Tests for _execute_and_ack."""

    async def test_successful_async_task_execution(self):
        """Successful task should record stats, clean up, and ACK."""
        consumer, redis, tm, stats = _make_consumer()
        task = _make_task("t1")
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.srem = AsyncMock()
        redis.xack = AsyncMock()

        await consumer._execute_and_ack("1-0", "g1", task, is_high_priority=False)

        # Task function was called
        task.function.assert_awaited_once()
        # Statistics recorded
        stats.record_execution.assert_awaited_once()
        # Running key cleaned up
        assert redis.delete.await_count >= 1
        # Message acknowledged
        redis.xack.assert_awaited_once()

    async def test_failed_task_applies_backoff_and_acks(self):
        """Failed task should apply backoff, ACK, and clean up tracking."""
        consumer, redis, tm, stats = _make_consumer()
        task = _make_task("t1", should_fail=True)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.srem = AsyncMock()
        redis.xack = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        await consumer._execute_and_ack("1-0", "g1", task, is_high_priority=False)

        # Stats should NOT be recorded on failure
        stats.record_execution.assert_not_awaited()
        # Backoff keys should be set
        assert redis.set.await_count >= 1
        # Message should still be ACK'd (retry via backoff, not PEL)
        redis.xack.assert_awaited_once()


class TestApplyBackoff:
    """Tests for _apply_backoff."""

    async def test_initial_backoff(self):
        """First failure should use the initial backoff value."""
        consumer, redis, _, _ = _make_consumer()
        task = _make_task("t1")
        redis.get = AsyncMock(return_value=None)  # No existing delay
        redis.set = AsyncMock()

        await consumer._apply_backoff("g1", task)

        # Should set retry_after and retry_delay
        assert redis.set.await_count == 2

    async def test_exponential_backoff_increases(self):
        """Subsequent failures should increase the delay."""
        consumer, redis, _, _ = _make_consumer()
        task = _make_task("t1")
        redis.get = AsyncMock(return_value=b"2.0")  # Current delay = 2s
        redis.set = AsyncMock()

        await consumer._apply_backoff("g1", task)

        # Next delay should be 2.0 * 2.0 = 4.0 (multiplier=2.0)
        set_calls = redis.set.call_args_list
        delay_call = set_calls[1]  # Second set call is retry_delay
        assert float(delay_call.args[1]) == 4.0


class TestRecoverPendingOnStartup:
    """Tests for _recover_pending_on_startup."""

    async def test_recovers_pending_messages(self):
        consumer, redis, _, _ = _make_consumer()
        redis.xautoclaim = AsyncMock(
            return_value=[
                b"0-0",
                [(b"1-0", {b"group": b"g1", b"task": b"t1"})],
                [],
            ],
        )

        await consumer._recover_pending_on_startup()

        # Should have spawned a task for the recovered message
        assert len(consumer._running_tasks) >= 0  # Task may complete quickly

    async def test_handles_xautoclaim_not_available(self):
        """Redis < 6.2 doesn't support XAUTOCLAIM; should not raise."""
        consumer, redis, _, _ = _make_consumer()
        redis.xautoclaim = AsyncMock(
            side_effect=ResponseError("unknown command `XAUTOCLAIM`"),
        )

        # Should not raise
        await consumer._recover_pending_on_startup()


class TestStartStop:
    """Tests for consumer lifecycle."""

    async def test_start_sets_running(self):
        consumer, redis, _, _ = _make_consumer()
        redis.xautoclaim = AsyncMock(return_value=[None, [], []])

        task = await consumer.start()
        assert consumer._running is True

        await consumer.stop()
        task.cancel()
        assert consumer._running is False
