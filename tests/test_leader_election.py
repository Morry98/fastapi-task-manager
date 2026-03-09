"""Tests for LeaderElector distributed leader election."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi_task_manager.leader_election import LeaderElector
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.worker_identity import WorkerIdentity


def _make_elector(redis=None):
    """Create a LeaderElector with mocked dependencies."""
    redis_client = redis or AsyncMock()
    key_builder = RedisKeyBuilder("test")
    worker = MagicMock(spec=WorkerIdentity)
    worker.redis_safe_id = "worker_1"
    worker.short_id = "w1"
    return LeaderElector(
        redis_client=redis_client,
        key_builder=key_builder,
        worker_identity=worker,
        heartbeat_interval=0.1,
    ), redis_client


class TestTryAcquireLeadership:
    """Tests for try_acquire_leadership."""

    async def test_acquire_success(self):
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)

        result = await elector.try_acquire_leadership()

        assert result is True
        assert elector.is_leader is True
        redis.set.assert_awaited_once_with(
            "test_leader_lock",
            "worker_1",
            nx=True,
            ex=1,  # math.ceil(heartbeat_interval(0.1) * 3)
        )
        # Clean up heartbeat task
        await elector.release_leadership()

    async def test_acquire_fails_when_lock_held(self):
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=None)

        result = await elector.try_acquire_leadership()

        assert result is False
        assert elector.is_leader is False

    async def test_is_leader_initially_false(self):
        elector, _ = _make_elector()
        assert elector.is_leader is False


class TestHeartbeatLoop:
    """Tests for the heartbeat renewal loop."""

    async def test_heartbeat_renews_lock(self):
        """When we own the lock, heartbeat renews it."""
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value="worker_1")

        await elector.try_acquire_leadership()
        # Let the heartbeat run at least once
        await asyncio.sleep(0.2)

        # Verify get was called to check ownership
        assert redis.get.await_count >= 1
        # Verify set was called for renewal (xx=True)
        renewal_calls = [c for c in redis.set.call_args_list if c.kwargs.get("xx") is True]
        assert len(renewal_calls) >= 1

        await elector.release_leadership()

    async def test_heartbeat_detects_lock_expired(self):
        """When lock disappears, leader steps down."""
        elector, redis = _make_elector()
        # First call succeeds (acquire), then get returns None (expired)
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)

        await elector.try_acquire_leadership()
        # Let the heartbeat detect the missing lock
        await asyncio.sleep(0.3)

        assert elector.is_leader is False

    async def test_heartbeat_detects_lock_stolen(self):
        """When another worker holds the lock, leader steps down."""
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        # Lock value belongs to another worker
        redis.get = AsyncMock(return_value=b"another_worker")

        await elector.try_acquire_leadership()
        await asyncio.sleep(0.3)

        assert elector.is_leader is False


class TestReleaseLeadership:
    """Tests for release_leadership."""

    async def test_release_deletes_lock_via_lua(self):
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=b"worker_1")
        redis.eval = AsyncMock(return_value=1)

        await elector.try_acquire_leadership()
        await elector.release_leadership()

        assert elector.is_leader is False
        redis.eval.assert_awaited_once()

    async def test_release_when_not_leader_is_noop(self):
        elector, redis = _make_elector()
        redis.eval = AsyncMock()

        await elector.release_leadership()

        assert elector.is_leader is False
        redis.eval.assert_not_awaited()

    async def test_release_handles_eval_exception(self):
        """release_leadership should not raise even if Redis errors."""
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=b"worker_1")
        redis.eval = AsyncMock(side_effect=ConnectionError("Redis down"))

        await elector.try_acquire_leadership()
        # Stop heartbeat manually to avoid background noise
        elector._is_leader = True
        # Should not raise
        await elector.release_leadership()
        assert elector.is_leader is False

    async def test_release_when_lock_not_owned(self):
        """When Lua script returns 0 (lock owned by another), should log and continue."""
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=b"worker_1")
        redis.eval = AsyncMock(return_value=0)  # Lock not owned

        await elector.try_acquire_leadership()
        elector._is_leader = True
        await elector.release_leadership()

        # Should complete without error
        assert elector.is_leader is False


class TestHeartbeatEdgeCases:
    """Tests for heartbeat edge cases (renewal failure, exceptions)."""

    async def test_heartbeat_renewal_failed(self):
        """When SET XX returns None (renewal failed), leader steps down."""
        elector, redis = _make_elector()
        # Acquire succeeds
        redis.set = AsyncMock(side_effect=[True, None])  # acquire ok, renewal fails
        redis.get = AsyncMock(return_value=b"worker_1")  # We own the lock

        await elector.try_acquire_leadership()
        assert elector.is_leader is True

        # Let heartbeat detect renewal failure
        await asyncio.sleep(0.3)

        assert elector.is_leader is False

    async def test_heartbeat_cancelled_error(self):
        """CancelledError in heartbeat loop should exit gracefully."""
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=b"worker_1")

        await elector.try_acquire_leadership()
        assert elector.is_leader is True

        # Cancel the heartbeat task directly
        elector._heartbeat_task.cancel()
        await asyncio.sleep(0.2)

        # The heartbeat should have exited; release should still work
        await elector.release_leadership()

    async def test_heartbeat_generic_exception(self):
        """Generic exception in heartbeat should cause leader to step down."""
        elector, redis = _make_elector()
        redis.set = AsyncMock(return_value=True)
        # get raises a generic exception after acquire
        redis.get = AsyncMock(side_effect=ConnectionError("Redis unavailable"))

        await elector.try_acquire_leadership()
        await asyncio.sleep(0.3)

        assert elector.is_leader is False
