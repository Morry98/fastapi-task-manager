"""Tests for Runner - orchestrates stream mode components."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_task_manager.config import Config
from fastapi_task_manager.runner import Runner


def _make_runner():
    """Create a Runner with mocked dependencies."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    config = Config(redis_host="localhost")
    tm = MagicMock()
    tm.config = config
    tm.task_groups = []
    runner = Runner(redis_client=redis, concurrent_tasks=2, task_manager=tm)
    return runner, redis


def _make_fake_asyncio_task():
    """Create a real asyncio.Task that completes immediately, usable with cancel/await."""

    async def noop():
        pass

    task = asyncio.ensure_future(noop())
    return task


class TestRunnerInit:
    """Tests for Runner initialization."""

    def test_initial_state(self):
        runner, _ = _make_runner()
        assert runner._leader_elector is None
        assert runner._coordinator is None
        assert runner._consumer is None
        assert runner._reconciler is None

    def test_worker_id_property(self):
        runner, _ = _make_runner()
        assert isinstance(runner.worker_id, str)

    def test_worker_started_at_property(self):
        runner, _ = _make_runner()
        assert isinstance(runner.worker_started_at, str)

    def test_is_leader_false_when_no_elector(self):
        runner, _ = _make_runner()
        assert runner.is_leader is False


class TestRunnerStart:
    """Tests for Runner.start."""

    @patch("fastapi_task_manager.runner.Reconciler")
    @patch("fastapi_task_manager.runner.Coordinator")
    @patch("fastapi_task_manager.runner.StreamConsumer")
    @patch("fastapi_task_manager.runner.LeaderElector")
    async def test_start_initializes_all_components(
        self,
        mock_leader,
        mock_consumer,
        mock_coordinator,
        mock_reconciler,
    ):
        runner, redis = _make_runner()

        # Mock component methods - start() must return a real awaitable task
        mock_consumer_inst = mock_consumer.return_value
        mock_consumer_inst.setup_consumer_groups = AsyncMock()
        mock_consumer_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_consumer_inst.stop = AsyncMock()

        mock_coordinator_inst = mock_coordinator.return_value
        mock_coordinator_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_coordinator_inst.stop = AsyncMock()

        mock_reconciler_inst = mock_reconciler.return_value
        mock_reconciler_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_reconciler_inst.stop = AsyncMock()

        mock_leader_inst = mock_leader.return_value
        mock_leader_inst.release_leadership = AsyncMock()

        await runner.start()

        mock_consumer_inst.setup_consumer_groups.assert_awaited_once()
        mock_coordinator_inst.start.assert_awaited_once()
        mock_consumer_inst.start.assert_awaited_once()
        mock_reconciler_inst.start.assert_awaited_once()

        # Clean up
        await runner.stop()

    async def test_start_raises_on_redis_ping_failure(self):
        runner, redis = _make_runner()
        redis.ping = AsyncMock(side_effect=ConnectionError("No connection"))

        with pytest.raises(ConnectionError):
            await runner.start()

    async def test_start_raises_on_falsy_ping(self):
        runner, redis = _make_runner()
        redis.ping = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError, match="falsy"):
            await runner.start()

    @patch("fastapi_task_manager.runner.Reconciler")
    @patch("fastapi_task_manager.runner.Coordinator")
    @patch("fastapi_task_manager.runner.StreamConsumer")
    @patch("fastapi_task_manager.runner.LeaderElector")
    async def test_start_skips_reconciler_when_disabled(
        self,
        mock_leader,
        mock_consumer,
        mock_coordinator,
        mock_reconciler,
    ):
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        config = Config(redis_host="localhost", reconciliation_enabled=False)
        tm = MagicMock()
        tm.config = config
        tm.task_groups = []
        runner = Runner(redis_client=redis, concurrent_tasks=2, task_manager=tm)

        mock_consumer_inst = mock_consumer.return_value
        mock_consumer_inst.setup_consumer_groups = AsyncMock()
        mock_consumer_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_consumer_inst.stop = AsyncMock()
        mock_coordinator.return_value.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_coordinator.return_value.stop = AsyncMock()
        mock_leader.return_value.release_leadership = AsyncMock()

        await runner.start()

        # Reconciler should not have been started
        mock_reconciler.return_value.start.assert_not_called()
        await runner.stop()


class TestRunnerStop:
    """Tests for Runner.stop."""

    async def test_stop_when_not_running_logs_warning(self):
        runner, _ = _make_runner()
        # Should not raise
        await runner.stop()

    @patch("fastapi_task_manager.runner.Reconciler")
    @patch("fastapi_task_manager.runner.Coordinator")
    @patch("fastapi_task_manager.runner.StreamConsumer")
    @patch("fastapi_task_manager.runner.LeaderElector")
    async def test_start_when_already_running_is_noop(
        self,
        mock_leader,
        mock_consumer,
        mock_coordinator,
        mock_reconciler,
    ):
        """Calling start() when already running should return early."""
        runner, redis = _make_runner()

        mock_consumer_inst = mock_consumer.return_value
        mock_consumer_inst.setup_consumer_groups = AsyncMock()
        mock_consumer_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_consumer_inst.stop = AsyncMock()

        mock_coordinator.return_value.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_coordinator.return_value.stop = AsyncMock()

        mock_reconciler.return_value.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_reconciler.return_value.stop = AsyncMock()

        mock_leader.return_value.release_leadership = AsyncMock()

        await runner.start()
        # Second call should be a noop (lines 84-86)
        await runner.start()

        # Consumer groups setup should only be called once
        mock_consumer_inst.setup_consumer_groups.assert_awaited_once()
        await runner.stop()

    @patch("fastapi_task_manager.runner.Reconciler")
    @patch("fastapi_task_manager.runner.Coordinator")
    @patch("fastapi_task_manager.runner.StreamConsumer")
    @patch("fastapi_task_manager.runner.LeaderElector")
    async def test_stop_cleans_up_all_components(
        self,
        mock_leader,
        mock_consumer,
        mock_coordinator,
        mock_reconciler,
    ):
        runner, redis = _make_runner()

        # Setup mocks with real awaitable tasks
        mock_consumer_inst = mock_consumer.return_value
        mock_consumer_inst.setup_consumer_groups = AsyncMock()
        mock_consumer_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_consumer_inst.stop = AsyncMock()

        mock_coordinator_inst = mock_coordinator.return_value
        mock_coordinator_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_coordinator_inst.stop = AsyncMock()

        mock_reconciler_inst = mock_reconciler.return_value
        mock_reconciler_inst.start = AsyncMock(return_value=_make_fake_asyncio_task())
        mock_reconciler_inst.stop = AsyncMock()

        mock_leader_inst = mock_leader.return_value
        mock_leader_inst.release_leadership = AsyncMock()

        await runner.start()
        await runner.stop()

        mock_reconciler_inst.stop.assert_awaited_once()
        mock_coordinator_inst.stop.assert_awaited_once()
        mock_consumer_inst.stop.assert_awaited_once()
        mock_leader_inst.release_leadership.assert_awaited_once()

        # References should be cleared
        assert runner._coordinator is None
        assert runner._consumer is None
        assert runner._reconciler is None
        assert runner._leader_elector is None
