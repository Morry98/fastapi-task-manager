"""Tests for task_router_services - service layer for API endpoints."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.exceptions import HTTPException

from fastapi_task_manager.config import Config
from fastapi_task_manager.schema.task import Task
from fastapi_task_manager.task_router_services import (
    _find_tasks,
    clear_statistics,
    disable_tasks,
    enable_tasks,
    get_config,
    get_health,
    get_registered_functions,
    get_task_groups,
    get_task_statistics,
    get_tasks,
    reset_retry,
    trigger_tasks,
)


def _make_task(name="t1"):
    async def dummy():
        pass

    return Task(function=dummy, expression="* * * * *", name=name)


def _make_group(name="g1", tasks=None, tags=None):
    group = MagicMock()
    group.name = name
    group.tags = tags or []
    group.tasks = tasks or []
    group.function_registry = {}
    return group


def _make_tm(task_groups=None, redis=None, config=None):
    """Create a mock TaskManager."""
    tm = MagicMock()
    tm.task_groups = task_groups or []
    tm.config = config or Config(redis_host="localhost")
    tm.redis_client = redis or AsyncMock()
    tm.runner = None
    return tm


class TestFindTasks:
    """Tests for _find_tasks helper."""

    def test_finds_all_tasks(self):
        task = _make_task()
        group = _make_group(tasks=[task])
        tm = _make_tm(task_groups=[group])

        result = _find_tasks(tm)
        assert len(result) == 1
        assert result[0] == (group, task)

    def test_filters_by_group_name(self):
        t1, t2 = _make_task("t1"), _make_task("t2")
        g1 = _make_group("g1", [t1])
        g2 = _make_group("g2", [t2])
        tm = _make_tm(task_groups=[g1, g2])

        result = _find_tasks(tm, task_group_name="g1")
        assert len(result) == 1
        assert result[0][1].name == "t1"

    def test_filters_by_task_name(self):
        t1, t2 = _make_task("t1"), _make_task("t2")
        group = _make_group(tasks=[t1, t2])
        tm = _make_tm(task_groups=[group])

        result = _find_tasks(tm, name="t2")
        assert len(result) == 1
        assert result[0][1].name == "t2"

    def test_filters_by_tag(self):
        t1 = _make_task("t1")
        t1.tags = ["important"]
        t2 = _make_task("t2")
        t2.tags = ["other"]
        group = _make_group(tasks=[t1, t2])
        tm = _make_tm(task_groups=[group])

        result = _find_tasks(tm, tag="important")
        assert len(result) == 1
        assert result[0][1].name == "t1"

    def test_raises_404_when_no_match(self):
        tm = _make_tm(task_groups=[])
        with pytest.raises(HTTPException) as exc_info:
            _find_tasks(tm)
        assert exc_info.value.status_code == 404


class TestGetTaskGroups:
    """Tests for get_task_groups."""

    def test_returns_all_groups(self):
        g1 = _make_group("g1", [_make_task()])
        g2 = _make_group("g2", [_make_task(), _make_task("t2")])
        tm = _make_tm(task_groups=[g1, g2])

        result = get_task_groups(tm)
        assert len(result) == 2
        assert result[0].name == "g1"
        assert result[0].task_count == 1
        assert result[1].task_count == 2

    def test_filters_by_name(self):
        g1 = _make_group("g1")
        g2 = _make_group("g2")
        tm = _make_tm(task_groups=[g1, g2])

        result = get_task_groups(tm, name="g2")
        assert len(result) == 1
        assert result[0].name == "g2"

    def test_filters_by_tag(self):
        g1 = _make_group("g1", tags=["prod"])
        g2 = _make_group("g2", tags=["dev"])
        tm = _make_tm(task_groups=[g1, g2])

        result = get_task_groups(tm, tag="prod")
        assert len(result) == 1
        assert result[0].name == "g1"


class TestGetTasks:
    """Tests for get_tasks."""

    async def test_filters_by_group_name(self):
        """get_tasks should skip groups that don't match the filter."""
        t1 = _make_task("t1")
        t2 = _make_task("t2")
        g1 = _make_group("g1", [t1])
        g2 = _make_group("g2", [t2])
        redis = MagicMock()
        pipe = MagicMock()
        pipe.get = MagicMock()
        pipe.exists = MagicMock()
        # Pipeline results: [next_run, disabled, retry_after, retry_delay, exists]
        pipe.execute = AsyncMock(
            return_value=[None, None, None, None, 0],
        )
        redis.pipeline.return_value = pipe

        tm = _make_tm(task_groups=[g1, g2], redis=redis)
        result = await get_tasks(tm, task_group_name="g2")

        assert len(result) == 1
        assert result[0].name == "t2"

    async def test_filters_by_tag(self):
        """get_tasks should skip tasks where tag doesn't match."""
        t1 = _make_task("t1")
        t1.tags = ["important"]
        t2 = _make_task("t2")
        t2.tags = ["other"]
        group = _make_group("g1", [t1, t2])
        redis = MagicMock()
        pipe = MagicMock()
        pipe.get = MagicMock()
        pipe.exists = MagicMock()
        pipe.execute = AsyncMock(
            return_value=[None, None, None, None, 0],
        )
        redis.pipeline.return_value = pipe

        tm = _make_tm(task_groups=[group], redis=redis)
        result = await get_tasks(tm, tag="important")

        assert len(result) == 1
        assert result[0].name == "t1"

    async def test_parses_retry_after_and_delay(self):
        """When retry_after and retry_delay are set, they should be parsed."""

        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = MagicMock()
        pipe = MagicMock()
        pipe.get = MagicMock()
        pipe.exists = MagicMock()
        future_ts = str(time.time() + 3600)
        pipe.execute = AsyncMock(
            return_value=[
                None,
                None,
                future_ts,  # retry_after
                "4.0",  # retry_delay
                0,
            ],
        )
        redis.pipeline.return_value = pipe

        tm = _make_tm(task_groups=[group], redis=redis)
        result = await get_tasks(tm)

        assert result[0].retry_after is not None
        assert result[0].retry_delay == 4.0

    async def test_returns_task_details_with_redis_data(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = MagicMock()
        pipe = MagicMock()
        pipe.get = MagicMock()
        pipe.exists = MagicMock()
        pipe.execute = AsyncMock(
            return_value=[
                "1700000060.0",  # next_run
                None,  # disabled
                None,  # retry_after
                None,  # retry_delay
                0,  # is_running (exists result)
            ],
        )
        redis.pipeline.return_value = pipe

        tm = _make_tm(task_groups=[group], redis=redis)
        result = await get_tasks(tm)

        assert len(result) == 1
        assert result[0].name == "t1"
        assert result[0].task_group_name == "g1"
        assert result[0].is_active is True
        assert result[0].is_running is False


class TestGetTaskStatistics:
    """Tests for get_task_statistics."""

    async def test_returns_statistics_for_task(self):
        """get_task_statistics should return parsed run history."""
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = AsyncMock()
        redis.xrange = AsyncMock(
            return_value=[
                ("1700000000000-0", {"ts": "100.0", "dur": "1.0"}),
                ("1700000001000-0", {"ts": "200.0", "dur": "2.0"}),
                ("1700000002000-0", {"ts": "300.0", "dur": "3.0"}),
            ],
        )

        tm = _make_tm(task_groups=[group], redis=redis)
        result = await get_task_statistics(tm, task_group_name="g1", task_name="t1")

        assert result.task_group_name == "g1"
        assert result.task_name == "t1"
        assert len(result.runs) == 3
        assert result.runs[0].durations_second == 1.0
        assert result.runs[2].durations_second == 3.0

    async def test_returns_empty_runs_when_no_stats(self):
        """get_task_statistics should return empty runs when no stats exist."""
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = AsyncMock()
        redis.xrange = AsyncMock(return_value=[])

        tm = _make_tm(task_groups=[group], redis=redis)
        result = await get_task_statistics(tm, task_group_name="g1", task_name="t1")

        assert result.runs == []

    async def test_raises_404_for_unknown_task(self):
        """get_task_statistics should raise 404 for non-existent task."""
        group = _make_group("g1", [_make_task("t1")])
        tm = _make_tm(task_groups=[group])

        with pytest.raises(HTTPException) as exc_info:
            await get_task_statistics(tm, task_group_name="g1", task_name="unknown")
        assert exc_info.value.status_code == 404


class TestDisableTasks:
    async def test_sets_disabled_flag(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = AsyncMock()
        tm = _make_tm(task_groups=[group], redis=redis)

        result = await disable_tasks(tm, task_group_name="g1")

        assert result.count == 1
        redis.set.assert_awaited_once()


class TestEnableTasks:
    async def test_deletes_disabled_flag(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = AsyncMock()
        tm = _make_tm(task_groups=[group], redis=redis)

        result = await enable_tasks(tm, task_group_name="g1")

        assert result.count == 1
        redis.delete.assert_awaited_once()


class TestResetRetry:
    async def test_deletes_retry_keys(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = AsyncMock()
        tm = _make_tm(task_groups=[group], redis=redis)

        result = await reset_retry(tm, task_group_name="g1")

        assert result.count == 1
        redis.delete.assert_awaited_once()


class TestTriggerTasks:
    async def test_sets_next_run_to_zero_and_clears_backoff(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = MagicMock()
        pipe = MagicMock()
        pipe.set = MagicMock()
        pipe.delete = MagicMock()
        pipe.execute = AsyncMock()
        redis.pipeline.return_value = pipe
        tm = _make_tm(task_groups=[group], redis=redis)

        result = await trigger_tasks(tm, task_group_name="g1")

        assert result.count == 1
        pipe.set.assert_called_once()
        pipe.delete.assert_called_once()


class TestClearStatistics:
    async def test_deletes_stats_stream_key(self):
        task = _make_task("t1")
        group = _make_group("g1", [task])
        redis = AsyncMock()
        tm = _make_tm(task_groups=[group], redis=redis)

        result = await clear_statistics(tm, task_group_name="g1")

        assert result.count == 1
        redis.delete.assert_awaited_once()


class TestGetHealth:
    async def test_healthy_when_running_and_redis_connected(self):
        tm = _make_tm()
        runner = MagicMock()
        runner.worker_id = "w1"
        runner.worker_started_at = "2024-01-01T00:00:00"
        runner.is_leader = True
        tm.runner = runner
        tm.redis_client = AsyncMock()
        tm.redis_client.ping = AsyncMock(return_value=True)

        result = await get_health(tm)

        assert result.status == "healthy"
        assert result.redis_connected is True
        assert result.worker_id == "w1"
        assert result.is_leader is True

    async def test_unhealthy_when_no_runner(self):
        tm = _make_tm()
        tm.runner = None
        tm.redis_client = AsyncMock()
        tm.redis_client.ping = AsyncMock(return_value=True)

        result = await get_health(tm)
        assert result.status == "unhealthy"

    async def test_unhealthy_when_redis_down(self):
        tm = _make_tm()
        tm.runner = MagicMock()
        tm.runner.worker_id = "w1"
        tm.runner.worker_started_at = "2024-01-01"
        tm.runner.is_leader = False
        tm.redis_client = AsyncMock()
        tm.redis_client.ping = AsyncMock(side_effect=ConnectionError("down"))

        result = await get_health(tm)
        assert result.status == "unhealthy"
        assert result.redis_connected is False


class TestGetConfig:
    def test_returns_config_response(self):
        config = Config(redis_host="localhost", redis_key_prefix="myapp")
        tm = _make_tm(config=config)

        result = get_config(tm)

        assert result.redis_key_prefix == "myapp"
        assert result.concurrent_tasks == 2
        assert result.leader_heartbeat_interval == 3.0


class TestGetRegisteredFunctions:
    def test_returns_registered_functions(self):
        group = _make_group("g1")
        group.function_registry = {"func_a": lambda: None, "func_b": lambda: None}
        tm = _make_tm(task_groups=[group])

        result = get_registered_functions(tm)

        assert result.count == 2
        names = [f.function_name for f in result.functions]
        assert "func_a" in names
        assert "func_b" in names

    def test_filters_by_group_name(self):
        g1 = _make_group("g1")
        g1.function_registry = {"func_a": lambda: None}
        g2 = _make_group("g2")
        g2.function_registry = {"func_b": lambda: None}
        tm = _make_tm(task_groups=[g1, g2])

        result = get_registered_functions(tm, task_group_name="g2")
        assert result.count == 1
        assert result.functions[0].function_name == "func_b"
