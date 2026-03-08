"""Tests for Reconciler - detects and recovers lost tasks."""

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from redis.exceptions import ResponseError

from fastapi_task_manager.config import Config
from fastapi_task_manager.leader_election import LeaderElector
from fastapi_task_manager.reconciler import Reconciler
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task


def _make_reconciler(task_groups=None, is_leader=True):
    """Create a Reconciler with mocked dependencies."""
    redis = AsyncMock()
    key_builder = RedisKeyBuilder("test")
    leader = MagicMock(spec=LeaderElector)
    leader.is_leader = is_leader
    config = Config(redis_host="localhost")
    tm = MagicMock()
    tm.config = config
    tm.task_groups = task_groups or []

    reconciler = Reconciler(
        redis_client=redis,
        key_builder=key_builder,
        leader_elector=leader,
        task_manager=tm,
    )
    return reconciler, redis


def _make_task(name="t1", high_priority=False):
    async def dummy():
        pass

    return Task(function=dummy, expression="* * * * *", name=name, high_priority=high_priority)


def _make_group(name="g1", tasks=None):
    group = MagicMock()
    group.name = name
    group.tasks = tasks or []
    return group


class TestCheckSingleTask:
    """Tests for _check_single_task."""

    async def test_skips_disabled_task(self):
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group(tasks=[task])
        redis.get = AsyncMock(return_value=b"1")  # disabled

        await reconciler._check_single_task(
            group,
            task,
            "test_scheduled_tasks",
            timedelta(seconds=30),
        )
        # Should not attempt to republish
        redis.xadd.assert_not_awaited()

    async def test_skips_already_scheduled_task(self):
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group(tasks=[task])
        redis.get = AsyncMock(return_value=None)  # not disabled
        redis.sismember = AsyncMock(return_value=True)  # is scheduled

        await reconciler._check_single_task(
            group,
            task,
            "test_scheduled_tasks",
            timedelta(seconds=30),
        )
        redis.xadd.assert_not_awaited()

    async def test_skips_running_task(self):
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group(tasks=[task])
        redis.get = AsyncMock(return_value=None)
        redis.sismember = AsyncMock(return_value=False)
        redis.exists = AsyncMock(return_value=True)  # running

        await reconciler._check_single_task(
            group,
            task,
            "test_scheduled_tasks",
            timedelta(seconds=30),
        )
        redis.xadd.assert_not_awaited()

    async def test_republishes_task_with_no_next_run(self):
        """Task with no next_run and not scheduled should be republished."""
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group(tasks=[task])
        redis.get = AsyncMock(return_value=None)  # disabled=None, next_run=None
        redis.sismember = AsyncMock(return_value=False)
        redis.exists = AsyncMock(return_value=False)
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()

        await reconciler._check_single_task(
            group,
            task,
            "test_scheduled_tasks",
            timedelta(seconds=30),
        )
        redis.xadd.assert_awaited_once()

    async def test_republishes_overdue_task(self):
        """Task with next_run far in the past should be republished."""
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group(tasks=[task])
        past = str(time.time() - 120)
        # disabled=None, next_run=past
        redis.get = AsyncMock(side_effect=[None, None, past.encode()])
        redis.sismember = AsyncMock(return_value=False)
        redis.exists = AsyncMock(return_value=False)
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()

        await reconciler._check_single_task(
            group,
            task,
            "test_scheduled_tasks",
            timedelta(seconds=30),
        )
        redis.xadd.assert_awaited_once()

    async def test_does_not_republish_not_yet_overdue(self):
        """Task barely past next_run but within threshold should not be republished."""
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group(tasks=[task])
        # Just 5 seconds past, threshold is 30
        recent_past = str(time.time() - 5)
        # _check_single_task calls get(disabled) then get(next_run)
        redis.get = AsyncMock(side_effect=[None, recent_past.encode()])
        redis.sismember = AsyncMock(return_value=False)
        redis.exists = AsyncMock(return_value=False)

        await reconciler._check_single_task(
            group,
            task,
            "test_scheduled_tasks",
            timedelta(seconds=30),
        )
        redis.xadd.assert_not_awaited()


class TestRepublishTask:
    """Tests for _republish_task."""

    async def test_publishes_to_low_stream_by_default(self):
        reconciler, redis = _make_reconciler()
        task = _make_task()
        group = _make_group()
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()

        await reconciler._republish_task(group, task)

        redis.xadd.assert_awaited_once()
        assert redis.xadd.call_args.args[0] == "test_task_stream_low"

    async def test_publishes_to_high_stream_for_high_priority(self):
        reconciler, redis = _make_reconciler()
        task = _make_task(high_priority=True)
        group = _make_group()
        redis.xadd = AsyncMock(return_value=b"1-0")
        redis.sadd = AsyncMock()

        await reconciler._republish_task(group, task)

        assert redis.xadd.call_args.args[0] == "test_task_stream_high"


class TestCleanupStaleTracking:
    """Tests for _cleanup_stale_tracking."""

    async def test_removes_stale_entries_for_unregistered_tasks(self):
        reconciler, redis = _make_reconciler(task_groups=[])
        redis.smembers = AsyncMock(return_value=[b"g1:t1"])
        redis.exists = AsyncMock(return_value=False)  # not running
        redis.srem = AsyncMock()

        await reconciler._cleanup_stale_tracking()

        redis.srem.assert_awaited_once()

    async def test_keeps_entries_for_running_tasks(self):
        reconciler, redis = _make_reconciler()
        redis.smembers = AsyncMock(return_value=[b"g1:t1"])
        redis.exists = AsyncMock(return_value=True)  # running

        await reconciler._cleanup_stale_tracking()

        redis.srem.assert_not_awaited()

    async def test_removes_malformed_entries(self):
        reconciler, redis = _make_reconciler()
        redis.smembers = AsyncMock(return_value=[b"malformed_no_colon"])
        redis.srem = AsyncMock()

        await reconciler._cleanup_stale_tracking()

        redis.srem.assert_awaited_once()


class TestReclaimStuckPending:
    """Tests for _reclaim_stuck_pending."""

    async def test_requeues_stuck_messages(self):
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            return_value=[
                {"message_id": b"1-0", "time_since_delivered": 60_000},
            ],
        )
        redis.xrange = AsyncMock(
            return_value=[(b"1-0", {b"group": b"g1", b"task": b"t1"})],
        )
        redis.xack = AsyncMock()
        redis.xadd = AsyncMock(return_value=b"2-0")

        await reconciler._reclaim_stuck_pending()

        # Should have ACK'd old and re-published
        assert redis.xack.await_count >= 1
        assert redis.xadd.await_count >= 1

    async def test_acks_orphan_message_already_trimmed(self):
        """When message data is gone (trimmed), just ACK the PEL entry."""
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            return_value=[
                {"message_id": b"1-0", "time_since_delivered": 60_000},
            ],
        )
        redis.xrange = AsyncMock(return_value=[])  # Message trimmed
        redis.xack = AsyncMock()

        await reconciler._reclaim_stuck_pending()

        redis.xack.assert_awaited()
        redis.xadd.assert_not_awaited()

    async def test_handles_xpending_not_available(self):
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            side_effect=ResponseError("unknown command"),
        )

        # Should not raise
        await reconciler._reclaim_stuck_pending()

    async def test_skips_messages_below_idle_threshold(self):
        """Messages not idle long enough should be skipped."""
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            return_value=[
                {"message_id": b"1-0", "time_since_delivered": 100},  # Below 30_000ms threshold
            ],
        )

        await reconciler._reclaim_stuck_pending()

        redis.xrange.assert_not_awaited()
        redis.xack.assert_not_awaited()

    async def test_skips_entries_without_message_id(self):
        """Entries with no message_id should be skipped."""
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            return_value=[
                {"time_since_delivered": 60_000},  # No message_id
            ],
        )

        await reconciler._reclaim_stuck_pending()

        redis.xrange.assert_not_awaited()

    async def test_handles_non_unknown_response_error(self):
        """Non-'unknown command' ResponseErrors are logged but don't crash."""
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            side_effect=ResponseError("SOME OTHER ERROR"),
        )

        # Should not raise
        await reconciler._reclaim_stuck_pending()

    async def test_handles_generic_exception(self):
        """Generic exceptions are caught and logged."""
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(
            side_effect=ConnectionError("Redis down"),
        )

        # Should not raise
        await reconciler._reclaim_stuck_pending()

    async def test_empty_pending_info_is_skipped(self):
        """When pending_info is empty, no requeue is attempted."""
        reconciler, redis = _make_reconciler()
        redis.xpending_range = AsyncMock(return_value=[])

        await reconciler._reclaim_stuck_pending()
        redis.xrange.assert_not_awaited()


class TestCheckOverdueTasks:
    """Tests for _check_overdue_tasks wrapper."""

    async def test_iterates_all_task_groups(self):
        task1 = _make_task("t1")
        task2 = _make_task("t2")
        g1 = _make_group("g1", [task1])
        g2 = _make_group("g2", [task2])
        reconciler, redis = _make_reconciler(task_groups=[g1, g2])
        # All tasks disabled (quick path)
        redis.get = AsyncMock(return_value=b"1")

        await reconciler._check_overdue_tasks()

        # get() should have been called for each task's disabled key
        assert redis.get.await_count == 2

    async def test_exception_in_single_task_does_not_stop_others(self):
        """An error checking one task should not prevent checking the rest."""
        task1 = _make_task("t1")
        task2 = _make_task("t2")
        g1 = _make_group("g1", [task1, task2])
        reconciler, redis = _make_reconciler(task_groups=[g1])
        # First call raises, second succeeds
        redis.get = AsyncMock(side_effect=[ConnectionError("oops"), b"1"])
        redis.sismember = AsyncMock(return_value=False)
        redis.exists = AsyncMock(return_value=False)

        # Should not raise
        await reconciler._check_overdue_tasks()


class TestRunLoop:
    """Tests for the _run reconciliation loop."""

    async def test_run_loop_executes_when_leader(self):
        import asyncio

        task = _make_task("t1")
        group = _make_group("g1", [task])
        reconciler, redis = _make_reconciler(task_groups=[group], is_leader=True)
        reconciler._task_manager.config.reconciliation_interval = 0.05
        # Make checks quick (task disabled)
        redis.get = AsyncMock(return_value=b"1")
        redis.smembers = AsyncMock(return_value=set())
        redis.xpending_range = AsyncMock(return_value=[])

        async def stop_after():
            await asyncio.sleep(0.15)
            await reconciler.stop()

        asyncio.create_task(stop_after())
        asyncio_task = await reconciler.start()
        await asyncio_task

    async def test_run_loop_skips_when_not_leader(self):
        import asyncio

        reconciler, redis = _make_reconciler(is_leader=False)
        reconciler._task_manager.config.reconciliation_interval = 0.05

        async def stop_after():
            await asyncio.sleep(0.15)
            await reconciler.stop()

        asyncio.create_task(stop_after())
        asyncio_task = await reconciler.start()
        await asyncio_task

        # Should not have called any reconciliation methods
        redis.smembers.assert_not_awaited()


class TestFindTask:
    """Tests for _find_task."""

    def test_finds_task_by_group_and_name(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        reconciler, _ = _make_reconciler(task_groups=[group])

        found = reconciler._find_task("g1", "t1")
        assert found is task

    def test_returns_none_for_missing(self):
        reconciler, _ = _make_reconciler(task_groups=[])
        assert reconciler._find_task("g1", "t1") is None


class TestStartStop:
    async def test_lifecycle(self):
        reconciler, _ = _make_reconciler()
        task = await reconciler.start()
        assert reconciler._running is True

        await reconciler.stop()
        task.cancel()
        assert reconciler._running is False
