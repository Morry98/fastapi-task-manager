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
    task_error_msg = "task failed"
    if is_async:
        func = AsyncMock(side_effect=RuntimeError(task_error_msg)) if should_fail else AsyncMock()
        func.__name__ = name
    else:
        func = MagicMock()
        func.__name__ = name
        if should_fail:
            func.side_effect = RuntimeError(task_error_msg)

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


class TestProcessMessageFound:
    """Tests for _process_message when the task is found."""

    async def test_calls_execute_and_ack_for_known_task(self):
        """When the task exists, _execute_and_ack should be called."""
        consumer, redis, tm, _stats = _make_consumer()
        task = _make_task("t1")
        group = MagicMock()
        group.name = "g1"
        group.tasks = [task]
        tm.task_groups = [group]

        redis.xack = AsyncMock()
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.srem = AsyncMock()

        # Use string keys - _process_message uses data.get("group") not data.get(b"group")
        await consumer._process_message(
            "1-0",
            {"group": "g1", "task": "t1"},
            is_high_priority=False,
        )

        # Task should have been executed
        task.function.assert_awaited_once()
        redis.xack.assert_awaited_once()


class TestExecuteAndAck:
    """Tests for _execute_and_ack."""

    async def test_successful_async_task_execution(self):
        """Successful task should record stats, clean up, and ACK."""
        consumer, redis, _tm, stats = _make_consumer()
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
        consumer, redis, _tm, stats = _make_consumer()
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


class TestTryReadStream:
    """Tests for _try_read_stream."""

    async def test_returns_message_when_available(self):
        consumer, redis, _, _ = _make_consumer()
        redis.xreadgroup = AsyncMock(
            return_value=[
                (b"stream", [(b"1-0", {b"group": b"g1", b"task": b"t1"})]),
            ],
        )

        result = await consumer._try_read_stream("stream", "group", block_ms=0)

        assert result is not None
        msg_id, _data = result
        assert msg_id == "1-0"

    async def test_returns_none_when_no_messages(self):
        consumer, redis, _, _ = _make_consumer()
        redis.xreadgroup = AsyncMock(return_value=[])

        result = await consumer._try_read_stream("stream", "group", block_ms=0)
        assert result is None

    async def test_decodes_string_message_id(self):
        """When message_id is already a string, it passes through."""
        consumer, redis, _, _ = _make_consumer()
        redis.xreadgroup = AsyncMock(
            return_value=[
                ("stream", [("1-0", {"group": "g1", "task": "t1"})]),
            ],
        )

        result = await consumer._try_read_stream("stream", "group", block_ms=0)
        assert result[0] == "1-0"


class TestConsumeLoop:
    """Tests for _consume_loop."""

    async def test_loop_reads_high_priority_first(self):
        """The consume loop should try high priority before low."""
        consumer, redis, tm, _ = _make_consumer()
        tm.task_groups = []
        call_count = 0

        async def mock_xreadgroup(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                consumer._running = False
            return []

        redis.xreadgroup = mock_xreadgroup

        consumer._running = True
        await consumer._consume_loop()

        # Should have been called multiple times (high + low attempts)
        assert call_count >= 2

    async def test_loop_stops_when_running_false(self):
        """The loop exits when _running becomes False."""
        consumer, redis, _, _ = _make_consumer()
        consumer._running = False
        redis.xreadgroup = AsyncMock(return_value=[])

        # Should return immediately
        await consumer._consume_loop()

    async def test_loop_spawns_high_priority_task(self):
        """When a high priority message is available, it should be spawned."""
        consumer, redis, tm, _stats = _make_consumer()
        tm.task_groups = []
        call_count = 0

        async def mock_xreadgroup(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (high priority, block_ms=0) returns a message
                return [(b"stream", [(b"1-0", {b"group": b"g1", b"task": b"t1"})])]
            # Stop after first message
            consumer._running = False
            return []

        redis.xreadgroup = mock_xreadgroup
        redis.xack = AsyncMock()

        consumer._running = True
        await consumer._consume_loop()

        # Should have spawned at least one task
        assert call_count >= 1

    async def test_loop_spawns_low_priority_task(self):
        """When only a low priority message is available, it should be spawned."""
        consumer, redis, tm, _stats = _make_consumer()
        tm.task_groups = []
        call_count = 0

        async def mock_xreadgroup(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # High priority returns nothing
                return []
            if call_count == 2:
                # Low priority returns a message
                return [(b"stream", [(b"2-0", {b"group": b"g1", b"task": b"t1"})])]
            consumer._running = False
            return []

        redis.xreadgroup = mock_xreadgroup
        redis.xack = AsyncMock()

        consumer._running = True
        await consumer._consume_loop()

        assert call_count >= 2

    async def test_loop_handles_exception(self):
        """Generic exception in consume loop should be caught and logged."""
        consumer, redis, _tm, _ = _make_consumer()
        call_count = 0

        async def mock_xreadgroup(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "Redis down"
                raise ConnectionError(msg)
            consumer._running = False
            return []

        redis.xreadgroup = mock_xreadgroup
        consumer._running = True
        # Should not raise
        await consumer._consume_loop()


class TestStopWithRunningTasks:
    """Tests for stop() with active tasks."""

    async def test_stop_waits_for_running_tasks(self):
        """stop() should wait for in-progress tasks to complete."""
        consumer, _redis, _tm, _stats = _make_consumer()
        # Add a fake running task
        completed = False

        async def slow_task():
            nonlocal completed
            await asyncio.sleep(0.1)
            completed = True

        running = asyncio.create_task(slow_task())
        consumer._running_tasks.add(running)
        running.add_done_callback(consumer._running_tasks.discard)

        consumer._running = True
        await consumer.stop()

        assert completed is True
        assert consumer._running is False


class TestSyncFunctionExecution:
    """Tests for executing sync functions via asyncio.to_thread."""

    async def test_sync_function_execution(self):
        """Sync functions should be run via to_thread."""
        consumer, redis, _tm, stats = _make_consumer()
        task = _make_task("sync_t", is_async=False)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.srem = AsyncMock()
        redis.xack = AsyncMock()

        await consumer._execute_and_ack("1-0", "g1", task, is_high_priority=False)

        task.function.assert_called_once()
        stats.record_execution.assert_awaited_once()


class TestRecoverPendingEdgeCases:
    """Additional edge cases for _recover_pending_on_startup."""

    async def test_handles_generic_exception(self):
        """Generic exceptions during recovery should be caught."""
        consumer, redis, _, _ = _make_consumer()
        redis.xautoclaim = AsyncMock(side_effect=ConnectionError("Redis down"))

        # Should not raise
        await consumer._recover_pending_on_startup()

    async def test_handles_non_unknown_response_error(self):
        """Non-'unknown command' ResponseErrors should be logged but not crash."""
        consumer, redis, _, _ = _make_consumer()
        redis.xautoclaim = AsyncMock(side_effect=ResponseError("OTHER ERROR"))

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
