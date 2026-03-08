"""Tests for TaskManager - entry point and lifecycle."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from fastapi_task_manager.config import Config
from fastapi_task_manager.task_group import TaskGroup
from fastapi_task_manager.task_manager import TaskManager


def _make_task_manager(app=None, config=None):
    """Create a TaskManager with mocked FastAPI app."""
    app = app or MagicMock(spec=FastAPI)
    app.router = MagicMock()
    config = config or Config(redis_host="localhost")
    return TaskManager(app=app, config=config)


class TestTaskManagerInit:
    """Tests for TaskManager initialization."""

    def test_initial_state(self):
        tm = _make_task_manager()
        assert tm.task_groups == []
        assert tm.runner is None
        assert tm.is_running is False

    def test_config_property(self):
        config = Config(redis_host="myhost")
        tm = _make_task_manager(config=config)
        assert tm.config.redis_host == "myhost"

    def test_redis_client_raises_when_not_started(self):
        tm = _make_task_manager()
        with pytest.raises(RuntimeError, match="not been started"):
            _ = tm.redis_client


class TestAddTaskGroup:
    """Tests for add_task_group."""

    def test_add_task_group(self):
        tm = _make_task_manager()
        group = TaskGroup(name="my_group")
        tm.add_task_group(group)
        assert len(tm.task_groups) == 1
        assert tm.task_groups[0].name == "my_group"

    def test_duplicate_group_name_raises(self):
        tm = _make_task_manager()
        tm.add_task_group(TaskGroup(name="dup"))
        with pytest.raises(RuntimeError, match="already exists"):
            tm.add_task_group(TaskGroup(name="dup"))

    def test_task_groups_returns_copy(self):
        tm = _make_task_manager()
        tm.add_task_group(TaskGroup(name="g"))
        groups = tm.task_groups
        groups.append(TaskGroup(name="extra"))
        assert len(tm.task_groups) == 1


class TestHealthMethods:
    """Tests for health check methods."""

    def test_is_running_false_without_runner(self):
        tm = _make_task_manager()
        assert tm.is_running is False

    def test_is_running_true_with_runner(self):
        tm = _make_task_manager()
        tm._runner = MagicMock()
        assert tm.is_running is True

    async def test_is_healthy_false_without_runner(self):
        tm = _make_task_manager()
        assert await tm.is_healthy() is False

    async def test_is_healthy_true_with_redis_ping(self):
        tm = _make_task_manager()
        tm._runner = MagicMock()
        tm._redis_client = AsyncMock()
        tm._redis_client.ping = AsyncMock(return_value=True)
        assert await tm.is_healthy() is True

    async def test_is_healthy_false_on_redis_error(self):
        tm = _make_task_manager()
        tm._runner = MagicMock()
        tm._redis_client = AsyncMock()
        tm._redis_client.ping = AsyncMock(side_effect=ConnectionError("down"))
        assert await tm.is_healthy() is False


class TestStartStop:
    """Tests for lifecycle management."""

    @patch("fastapi_task_manager.task_manager.Runner")
    @patch("fastapi_task_manager.task_manager.Redis")
    async def test_start_creates_redis_and_runner(self, mock_redis_cls, mock_runner_cls):
        tm = _make_task_manager()
        mock_redis_inst = AsyncMock()
        mock_redis_cls.return_value = mock_redis_inst
        mock_redis_inst.hgetall = AsyncMock(return_value={})

        mock_runner_inst = AsyncMock()
        mock_runner_cls.return_value = mock_runner_inst
        mock_runner_inst.start = AsyncMock()

        await tm.start()

        assert tm._redis_client is mock_redis_inst
        assert tm._runner is mock_runner_inst
        mock_runner_inst.start.assert_awaited_once()

    @patch("fastapi_task_manager.task_manager.Runner")
    @patch("fastapi_task_manager.task_manager.Redis")
    async def test_stop_cleans_up(self, mock_redis_cls, mock_runner_cls):
        tm = _make_task_manager()
        mock_redis_inst = AsyncMock()
        mock_redis_cls.return_value = mock_redis_inst
        mock_redis_inst.hgetall = AsyncMock(return_value={})

        mock_runner_inst = AsyncMock()
        mock_runner_cls.return_value = mock_runner_inst
        mock_runner_inst.start = AsyncMock()
        mock_runner_inst.stop = AsyncMock()
        mock_redis_inst.aclose = AsyncMock()

        await tm.start()
        await tm.stop()

        mock_runner_inst.stop.assert_awaited_once()
        mock_redis_inst.aclose.assert_awaited_once()
        assert tm._runner is None
        assert tm._redis_client is None

    @patch("fastapi_task_manager.task_manager.Runner")
    @patch("fastapi_task_manager.task_manager.Redis")
    async def test_start_when_already_running_is_noop(self, mock_redis_cls, mock_runner_cls):
        tm = _make_task_manager()
        mock_redis_inst = AsyncMock()
        mock_redis_cls.return_value = mock_redis_inst
        mock_redis_inst.hgetall = AsyncMock(return_value={})
        mock_runner_inst = AsyncMock()
        mock_runner_cls.return_value = mock_runner_inst
        mock_runner_inst.start = AsyncMock()

        await tm.start()
        await tm.start()  # Second call should be a noop

        # Runner.start should only be called once
        mock_runner_inst.start.assert_awaited_once()
        await tm.stop()

    async def test_stop_when_not_running_is_noop(self):
        tm = _make_task_manager()
        # Should not raise
        await tm.stop()


class TestLoadDynamicTasks:
    """Tests for _load_dynamic_tasks."""

    async def test_loads_persisted_tasks(self):
        tm = _make_task_manager()
        group = TaskGroup(name="g1")

        @group.register_function("my_func")
        async def my_func():
            pass

        tm.add_task_group(group)

        redis = AsyncMock()
        definition = json.dumps(
            {
                "task_group_name": "g1",
                "function_name": "my_func",
                "cron_expression": "* * * * *",
                "name": "loaded_task",
            },
        )
        redis.hgetall = AsyncMock(return_value={b"g1:loaded_task": definition.encode()})
        tm._redis_client = redis

        await tm._load_dynamic_tasks()

        assert len(group.tasks) == 1
        assert group.tasks[0].name == "loaded_task"
        assert group.tasks[0].dynamic is True

    async def test_skips_missing_group(self):
        tm = _make_task_manager()
        redis = AsyncMock()
        definition = json.dumps(
            {
                "task_group_name": "nonexistent",
                "function_name": "func",
                "cron_expression": "* * * * *",
                "name": "task",
            },
        )
        redis.hgetall = AsyncMock(return_value={b"key": definition.encode()})
        tm._redis_client = redis

        # Should not raise
        await tm._load_dynamic_tasks()

    async def test_skips_unregistered_function(self):
        tm = _make_task_manager()
        group = TaskGroup(name="g1")
        tm.add_task_group(group)

        redis = AsyncMock()
        definition = json.dumps(
            {
                "task_group_name": "g1",
                "function_name": "unregistered",
                "cron_expression": "* * * * *",
                "name": "task",
            },
        )
        redis.hgetall = AsyncMock(return_value={b"key": definition.encode()})
        tm._redis_client = redis

        await tm._load_dynamic_tasks()
        assert len(group.tasks) == 0

    async def test_no_redis_client_is_noop(self):
        tm = _make_task_manager()
        tm._redis_client = None
        # Should not raise
        await tm._load_dynamic_tasks()

    async def test_empty_redis_hash_is_noop(self):
        tm = _make_task_manager()
        redis = AsyncMock()
        redis.hgetall = AsyncMock(return_value={})
        tm._redis_client = redis
        await tm._load_dynamic_tasks()

    async def test_load_catches_exception_in_definition(self):
        """Malformed JSON in a definition should be caught and logged."""
        tm = _make_task_manager()
        group = TaskGroup(name="g1")

        @group.register_function("my_func")
        async def my_func():
            pass

        tm.add_task_group(group)

        redis = AsyncMock()
        # Invalid JSON triggers an exception during loading
        redis.hgetall = AsyncMock(return_value={b"g1:bad": b"not valid json"})
        tm._redis_client = redis

        # Should not raise
        await tm._load_dynamic_tasks()
        assert len(group.tasks) == 0


class TestRedisClientProperty:
    """Tests for redis_client property."""

    def test_returns_client_when_started(self):
        """When started, redis_client returns the client instance."""
        tm = _make_task_manager()
        mock_redis = AsyncMock()
        tm._redis_client = mock_redis
        assert tm.redis_client is mock_redis


class TestHealthCheck:
    """Tests for health_check method."""

    async def test_health_check_delegates_to_get_health(self):
        """health_check() should return a HealthResponse."""
        tm = _make_task_manager()
        tm._runner = MagicMock()
        tm._runner.worker_id = "w1"
        tm._runner.worker_started_at = "2024-01-01T00:00:00"
        tm._runner.is_leader = False
        tm._redis_client = AsyncMock()
        tm._redis_client.ping = AsyncMock(return_value=True)

        result = await tm.health_check()
        assert result.status == "healthy"


class TestAppendToAppLifecycle:
    """Tests for append_to_app_lifecycle."""

    async def test_sets_lifespan_on_app(self):
        """append_to_app_lifecycle should set lifespan_context on the app router."""
        app = FastAPI()
        tm = _make_task_manager(app=app)
        original_lifespan = getattr(app.router, "lifespan_context", None)
        tm.append_to_app_lifecycle(app)
        # The lifespan_context should be replaced
        assert app.router.lifespan_context is not original_lifespan

    @patch("fastapi_task_manager.task_manager.Runner")
    @patch("fastapi_task_manager.task_manager.Redis")
    async def test_lifecycle_starts_and_stops(self, mock_redis_cls, mock_runner_cls):
        """The lifespan should call start() and stop()."""
        app = FastAPI()
        config = Config(redis_host="localhost")
        tm = TaskManager(app=app, config=config)

        mock_redis_inst = AsyncMock()
        mock_redis_cls.return_value = mock_redis_inst
        mock_redis_inst.hgetall = AsyncMock(return_value={})
        mock_redis_inst.aclose = AsyncMock()

        mock_runner_inst = AsyncMock()
        mock_runner_cls.return_value = mock_runner_inst
        mock_runner_inst.start = AsyncMock()
        mock_runner_inst.stop = AsyncMock()

        tm.append_to_app_lifecycle(app)

        # Run the lifespan context manager

        lifespan = app.router.lifespan_context
        async with lifespan(app):
            assert tm._runner is not None

        mock_runner_inst.stop.assert_awaited_once()

    @patch("fastapi_task_manager.task_manager.Runner")
    @patch("fastapi_task_manager.task_manager.Redis")
    async def test_lifecycle_chains_existing_lifespan(self, mock_redis_cls, mock_runner_cls):
        """When the app already has a lifespan, it should be chained."""
        from contextlib import asynccontextmanager

        existing_called = False

        @asynccontextmanager
        async def existing_lifespan(app):
            nonlocal existing_called
            existing_called = True
            yield

        app = FastAPI()
        app.router.lifespan_context = existing_lifespan
        config = Config(redis_host="localhost")
        tm = TaskManager(app=app, config=config)

        mock_redis_inst = AsyncMock()
        mock_redis_cls.return_value = mock_redis_inst
        mock_redis_inst.hgetall = AsyncMock(return_value={})
        mock_redis_inst.aclose = AsyncMock()

        mock_runner_inst = AsyncMock()
        mock_runner_cls.return_value = mock_runner_inst
        mock_runner_inst.start = AsyncMock()
        mock_runner_inst.stop = AsyncMock()

        tm.append_to_app_lifecycle(app)

        lifespan = app.router.lifespan_context
        async with lifespan(app):
            pass

        assert existing_called is True


class TestGetManagerRouter:
    """Tests for get_manager_router."""

    def test_router_has_expected_routes(self):
        tm = _make_task_manager()
        router = tm.get_manager_router()
        paths = [route.path for route in router.routes]

        assert "/task-groups" in paths
        assert "/tasks" in paths
        assert "/health" in paths
        assert "/config" in paths
        assert "/tasks/disable" in paths
        assert "/tasks/enable" in paths
        assert "/tasks/reset-retry" in paths
        assert "/tasks/trigger" in paths
        assert "/tasks/statistics" in paths
        assert "/functions" in paths
