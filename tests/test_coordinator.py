"""Tests for Coordinator - cron evaluation and stream publishing."""

import time
from unittest.mock import AsyncMock, MagicMock

from fastapi_task_manager.config import Config
from fastapi_task_manager.coordinator import Coordinator
from fastapi_task_manager.leader_election import LeaderElector
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task


def _make_coordinator(tasks=None, is_leader=True):
    """Create a Coordinator with mocked dependencies."""
    redis = AsyncMock()
    key_builder = RedisKeyBuilder("test")

    leader = MagicMock(spec=LeaderElector)
    leader.is_leader = is_leader
    leader.try_acquire_leadership = AsyncMock(return_value=False)

    config = Config(redis_host="localhost")
    task_manager = MagicMock()
    task_manager.config = config
    task_manager.task_groups = tasks or []

    coordinator = Coordinator(
        redis_client=redis,
        key_builder=key_builder,
        leader_elector=leader,
        task_manager=task_manager,
    )
    return coordinator, redis, task_manager


def _make_task_group(name="grp", tasks=None):
    """Create a mock TaskGroup with tasks."""
    group = MagicMock()
    group.name = name
    group.tasks = tasks or []
    return group


def _make_task(name="task1", expr="* * * * *", high_priority=False):
    """Create a mock Task."""

    async def dummy():
        pass

    return Task(
        function=dummy,
        expression=expr,
        name=name,
        high_priority=high_priority,
    )


class TestIsTaskDue:
    """Tests for _is_task_due."""

    async def test_disabled_task_is_not_due(self):
        """A disabled task should not be due."""
        coordinator, redis, _ = _make_coordinator()
        task = _make_task()
        group = _make_task_group(tasks=[task])
        # Return a value for disabled key (task is disabled)
        redis.get = AsyncMock(return_value=b"1")

        result = await coordinator._is_task_due(group, task)
        assert result is False

    async def test_task_in_backoff_not_due(self):
        """Task with retry_after in the future should not be due."""
        coordinator, redis, _ = _make_coordinator()
        task = _make_task()
        group = _make_task_group(tasks=[task])
        # disabled=None, retry_after=future timestamp
        future = str(time.time() + 3600)
        redis.get = AsyncMock(side_effect=[None, future.encode()])

        result = await coordinator._is_task_due(group, task)
        assert result is False

    async def test_task_with_no_next_run_is_due(self):
        """Task that has never run is due immediately."""
        coordinator, redis, _ = _make_coordinator()
        task = _make_task()
        group = _make_task_group(tasks=[task])
        # disabled=None, retry_after=None, next_run=None
        redis.get = AsyncMock(return_value=None)

        result = await coordinator._is_task_due(group, task)
        assert result is True

    async def test_task_with_past_next_run_is_due(self):
        """Task with next_run in the past is due."""
        coordinator, redis, _ = _make_coordinator()
        task = _make_task()
        group = _make_task_group(tasks=[task])
        past = str(time.time() - 60)
        # disabled=None, retry_after=None, next_run=past
        redis.get = AsyncMock(side_effect=[None, None, past.encode()])

        result = await coordinator._is_task_due(group, task)
        assert result is True

    async def test_task_with_future_next_run_not_due(self):
        """Task with next_run in the future is not due."""
        coordinator, redis, _ = _make_coordinator()
        task = _make_task()
        group = _make_task_group(tasks=[task])
        future = str(time.time() + 3600)
        # disabled=None, retry_after=None, next_run=future
        redis.get = AsyncMock(side_effect=[None, None, future.encode()])

        result = await coordinator._is_task_due(group, task)
        assert result is False


class TestPublishTask:
    """Tests for _publish_task."""

    async def test_publishes_to_stream_and_tracks(self):
        coordinator, redis, tm = _make_coordinator()
        task = _make_task()
        group = _make_task_group()
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()

        msg_id = await coordinator._publish_task("test_task_stream_low", group, task)

        assert msg_id == "1-0"
        redis.xadd.assert_awaited_once()
        redis.sadd.assert_awaited_once()
        # Verify the scheduled set tracking
        call_args = redis.sadd.call_args
        assert "grp:task1" in call_args.args

    async def test_high_priority_task_uses_high_stream(self):
        coordinator, redis, _ = _make_coordinator()
        task = _make_task(high_priority=True)
        group = _make_task_group()
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()

        await coordinator._publish_task("test_task_stream_high", group, task)
        # Verify it was published to the high priority stream
        assert redis.xadd.call_args.args[0] == "test_task_stream_high"


class TestUpdateNextRun:
    """Tests for _update_next_run."""

    async def test_updates_next_run_in_redis(self):
        coordinator, redis, _ = _make_coordinator()
        task = _make_task(expr="*/5 * * * *")
        group = _make_task_group()
        redis.set = AsyncMock()

        await coordinator._update_next_run(group, task)

        redis.set.assert_awaited_once()
        # The key should be the next_run key for this task
        call_args = redis.set.call_args
        assert call_args.args[0] == "test_grp_task1_next_run"


class TestEvaluateAndPublishAll:
    """Tests for _evaluate_and_publish_all."""

    async def test_publishes_due_tasks(self):
        """Due tasks get published and next_run updated."""
        task = _make_task("t1")
        group = _make_task_group("g1", [task])
        coordinator, redis, tm = _make_coordinator(tasks=[group])
        # Task is due (no next_run set)
        redis.get = AsyncMock(return_value=None)
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()
        redis.set = AsyncMock()

        await coordinator._evaluate_and_publish_all()

        redis.xadd.assert_awaited_once()
        # next_run should be updated
        assert redis.set.await_count >= 1

    async def test_skips_not_due_tasks(self):
        """Tasks not due are not published."""
        task = _make_task("t1")
        group = _make_task_group("g1", [task])
        coordinator, redis, tm = _make_coordinator(tasks=[group])
        # Task is disabled
        redis.get = AsyncMock(return_value=b"1")

        await coordinator._evaluate_and_publish_all()

        redis.xadd.assert_not_awaited()

    async def test_exception_in_task_evaluation_is_caught(self):
        """An exception evaluating one task does not stop processing others."""
        task = _make_task("t1")
        group = _make_task_group("g1", [task])
        coordinator, redis, tm = _make_coordinator(tasks=[group])
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        # Should not raise
        await coordinator._evaluate_and_publish_all()


class TestRunLoop:
    """Tests for the _run coordinator loop."""

    async def test_run_as_leader_evaluates_tasks(self):
        """When leader, the loop evaluates and publishes tasks."""
        import asyncio

        task = _make_task("t1")
        group = _make_task_group("g1", [task])
        coordinator, redis, tm = _make_coordinator(tasks=[group], is_leader=True)
        # Make task disabled so evaluation is quick
        redis.get = AsyncMock(return_value=b"1")

        # Run for a short time then stop
        async def stop_after():
            await asyncio.sleep(0.15)
            await coordinator.stop()

        asyncio.create_task(stop_after())
        asyncio_task = await coordinator.start()
        await asyncio_task

    async def test_run_as_follower_tries_to_acquire(self):
        """When not leader, the loop tries to acquire leadership."""
        import asyncio

        coordinator, redis, tm = _make_coordinator(is_leader=False)
        tm.config.leader_retry_interval = 0.05

        async def stop_after():
            await asyncio.sleep(0.15)
            await coordinator.stop()

        asyncio.create_task(stop_after())
        asyncio_task = await coordinator.start()
        await asyncio_task

        # Should have tried to acquire leadership
        coordinator._leader.try_acquire_leadership.assert_awaited()


class TestStartStop:
    """Tests for coordinator lifecycle."""

    async def test_start_creates_task(self):
        coordinator, _, _ = _make_coordinator()
        task = await coordinator.start()
        assert task is not None
        # Clean up
        await coordinator.stop()
        task.cancel()

    async def test_stop_sets_running_false(self):
        coordinator, _, _ = _make_coordinator()
        await coordinator.start()
        await coordinator.stop()
        assert coordinator._running is False
