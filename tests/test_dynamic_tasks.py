"""Tests for dynamic task creation and deletion at runtime."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.exceptions import HTTPException

from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import CreateDynamicTaskRequest
from fastapi_task_manager.task_group import TaskGroup
from fastapi_task_manager.task_manager import TaskManager
from fastapi_task_manager.task_router_services import (
    create_dynamic_task,
    delete_dynamic_task,
    get_registered_functions,
)

# ---------------------------------------------------------------------------
# TaskGroup function registry tests
# ---------------------------------------------------------------------------


class TestFunctionRegistry:
    """Tests for the function registry on TaskGroup."""

    def test_register_function_decorator(self):
        """register_function stores callable in the registry."""
        group = TaskGroup(name="test_group")

        @group.register_function("my_func")
        async def my_func():
            pass

        assert "my_func" in group.function_registry
        assert group.function_registry["my_func"] is my_func

    def test_register_function_uses_func_name_as_default(self):
        """When no name is given, the function's __name__ is used."""
        group = TaskGroup(name="test_group")

        @group.register_function()
        async def some_task():
            pass

        assert "some_task" in group.function_registry

    def test_register_function_duplicate_raises(self):
        """Registering the same name twice raises RuntimeError."""
        group = TaskGroup(name="test_group")

        @group.register_function("dup")
        async def func_a():
            pass

        with pytest.raises(RuntimeError, match="already registered"):

            @group.register_function("dup")
            async def func_b():
                pass

    def test_add_task_registers_function_by_default(self):
        """The add_task decorator also registers the function in the registry."""
        group = TaskGroup(name="test_group")

        @group.add_task("* * * * *", name="auto_reg")
        async def auto_registered():
            pass

        assert "auto_reg" in group.function_registry

    def test_add_task_register_false_skips_registry(self):
        """Setting register=False prevents add_task from registering the function."""
        group = TaskGroup(name="test_group")

        @group.add_task("* * * * *", name="no_reg", register=False)
        async def not_registered():
            pass

        assert "no_reg" not in group.function_registry
        # But the task itself still exists
        assert len(group.tasks) == 1


# ---------------------------------------------------------------------------
# TaskGroup dynamic task add/remove tests
# ---------------------------------------------------------------------------


class TestDynamicTaskAddRemove:
    """Tests for adding and removing dynamic tasks on TaskGroup."""

    def _make_group_with_func(self):
        """Helper: create a TaskGroup with a registered function."""
        group = TaskGroup(name="test_group", tags=["base"])

        @group.register_function("worker")
        async def worker(param: str = "default"):
            pass

        return group

    def test_add_dynamic_task_basic(self):
        """add_dynamic_task creates a task and appends it to the group."""
        group = self._make_group_with_func()
        task = group.add_dynamic_task(
            function_name="worker",
            cron_expression="0 9 * * MON",
            kwargs={"param": "hello"},
            name="monday_worker",
        )

        assert task.name == "monday_worker"
        assert task.dynamic is True
        assert task.function_name == "worker"
        assert task.expression == "0 9 * * MON"
        assert task.kwargs == {"param": "hello"}
        assert len(group.tasks) == 1

    def test_add_dynamic_task_generates_name_when_not_provided(self):
        """When no name is given, a hash-based name is generated."""
        group = self._make_group_with_func()
        task = group.add_dynamic_task(
            function_name="worker",
            cron_expression="*/5 * * * *",
        )

        assert task.name.startswith("worker__")
        assert task.dynamic is True

    def test_add_dynamic_task_unregistered_function_raises(self):
        """Referencing a non-registered function raises RuntimeError."""
        group = TaskGroup(name="test_group")

        with pytest.raises(RuntimeError, match="not registered"):
            group.add_dynamic_task(
                function_name="nonexistent",
                cron_expression="* * * * *",
            )

    def test_add_dynamic_task_duplicate_name_raises(self):
        """Adding a task with a name that already exists raises RuntimeError."""
        group = self._make_group_with_func()
        group.add_dynamic_task(
            function_name="worker",
            cron_expression="* * * * *",
            name="unique_task",
        )

        with pytest.raises(RuntimeError, match="already exists"):
            group.add_dynamic_task(
                function_name="worker",
                cron_expression="*/5 * * * *",
                name="unique_task",
            )

    def test_add_dynamic_task_merges_tags(self):
        """Dynamic task tags are merged with group-level tags."""
        group = self._make_group_with_func()
        task = group.add_dynamic_task(
            function_name="worker",
            cron_expression="* * * * *",
            name="tagged",
            tags=["custom"],
        )

        assert "base" in task.tags
        assert "custom" in task.tags

    def test_remove_dynamic_task(self):
        """remove_dynamic_task removes a dynamic task from the group."""
        group = self._make_group_with_func()
        group.add_dynamic_task(
            function_name="worker",
            cron_expression="* * * * *",
            name="removable",
        )
        assert len(group.tasks) == 1

        removed = group.remove_dynamic_task("removable")
        assert removed.name == "removable"
        assert len(group.tasks) == 0

    def test_remove_static_task_raises(self):
        """Cannot remove a static task (registered via decorator)."""
        group = TaskGroup(name="test_group")

        @group.add_task("* * * * *", name="static_task")
        async def static():
            pass

        # The internal name includes hashes, so use the actual task name
        static_internal_name = group.tasks[0].name
        with pytest.raises(RuntimeError, match="static and cannot be removed"):
            group.remove_dynamic_task(static_internal_name)

    def test_remove_nonexistent_task_raises(self):
        """Removing a non-existent task raises RuntimeError."""
        group = TaskGroup(name="test_group")

        with pytest.raises(RuntimeError, match="not found"):
            group.remove_dynamic_task("ghost")


# ---------------------------------------------------------------------------
# Redis key builder tests
# ---------------------------------------------------------------------------


class TestRedisKeyBuilder:
    """Test the new dynamic_tasks_key method."""

    def test_dynamic_tasks_key(self):
        builder = RedisKeyBuilder("myapp")
        assert builder.dynamic_tasks_key() == "myapp_dynamic_tasks"


# ---------------------------------------------------------------------------
# Service layer tests (mocked Redis)
# ---------------------------------------------------------------------------


def _make_mock_task_manager(group: TaskGroup):
    """Create a mock TaskManager with a single TaskGroup."""
    tm = MagicMock()
    tm.task_groups = [group]
    tm.config = MagicMock()
    tm.config.redis_key_prefix = "test"
    # Mock Redis client
    redis_mock = AsyncMock()
    tm.redis_client = redis_mock
    return tm


class TestCreateDynamicTaskService:
    """Tests for the create_dynamic_task service function."""

    async def test_create_success(self):
        """Successfully create a dynamic task via service function."""
        group = TaskGroup(name="reports")

        @group.register_function("gen_report")
        async def gen_report(fmt: str = "pdf"):
            pass

        tm = _make_mock_task_manager(group)

        request = CreateDynamicTaskRequest(
            task_group_name="reports",
            function_name="gen_report",
            cron_expression="0 9 * * *",
            kwargs={"fmt": "csv"},
            name="daily_csv",
        )

        result = await create_dynamic_task(tm, request)

        assert result.task_name == "daily_csv"
        assert result.function_name == "gen_report"
        assert result.cron_expression == "0 9 * * *"
        assert result.kwargs == {"fmt": "csv"}
        # Task was added to the group
        assert len(group.tasks) == 1
        assert group.tasks[0].dynamic is True
        # Definition persisted to Redis
        tm.redis_client.hset.assert_called_once()

    async def test_create_unknown_group_returns_404(self):
        """Creating a task in a non-existent group raises 404."""
        group = TaskGroup(name="reports")
        tm = _make_mock_task_manager(group)

        request = CreateDynamicTaskRequest(
            task_group_name="nonexistent",
            function_name="x",
            cron_expression="* * * * *",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_dynamic_task(tm, request)
        assert exc_info.value.status_code == 404

    async def test_create_unregistered_function_returns_400(self):
        """Referencing an unregistered function raises 400."""
        group = TaskGroup(name="reports")
        tm = _make_mock_task_manager(group)

        request = CreateDynamicTaskRequest(
            task_group_name="reports",
            function_name="ghost",
            cron_expression="* * * * *",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_dynamic_task(tm, request)
        assert exc_info.value.status_code == 400

    async def test_create_invalid_cron_returns_400(self):
        """An invalid cron expression raises 400."""
        group = TaskGroup(name="reports")

        @group.register_function("func")
        async def func():
            pass

        tm = _make_mock_task_manager(group)

        request = CreateDynamicTaskRequest(
            task_group_name="reports",
            function_name="func",
            cron_expression="not a cron",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_dynamic_task(tm, request)
        assert exc_info.value.status_code == 400

    async def test_create_duplicate_name_returns_409(self):
        """Duplicate task name raises 409 Conflict."""
        group = TaskGroup(name="reports")

        @group.register_function("func")
        async def func():
            pass

        tm = _make_mock_task_manager(group)

        request = CreateDynamicTaskRequest(
            task_group_name="reports",
            function_name="func",
            cron_expression="* * * * *",
            name="dup",
        )

        await create_dynamic_task(tm, request)

        with pytest.raises(HTTPException) as exc_info:
            await create_dynamic_task(tm, request)
        assert exc_info.value.status_code == 409


class TestDeleteDynamicTaskService:
    """Tests for the delete_dynamic_task service function."""

    async def test_delete_success(self):
        """Successfully delete a dynamic task via service function."""
        group = TaskGroup(name="reports")

        @group.register_function("func")
        async def func():
            pass

        group.add_dynamic_task(
            function_name="func",
            cron_expression="* * * * *",
            name="to_delete",
        )

        tm = _make_mock_task_manager(group)

        result = await delete_dynamic_task(tm, "reports", "to_delete")

        assert result.task_name == "to_delete"
        assert len(group.tasks) == 0
        # Redis cleanup was called
        tm.redis_client.delete.assert_called_once()
        tm.redis_client.hdel.assert_called_once()

    async def test_delete_static_task_returns_400(self):
        """Deleting a static task raises 400."""
        group = TaskGroup(name="reports")

        @group.add_task("* * * * *", name="static")
        async def static():
            pass

        tm = _make_mock_task_manager(group)
        # The static task internal name includes hashes
        static_name = group.tasks[0].name

        with pytest.raises(HTTPException) as exc_info:
            await delete_dynamic_task(tm, "reports", static_name)
        assert exc_info.value.status_code == 400

    async def test_delete_nonexistent_returns_404(self):
        """Deleting a non-existent task raises 404."""
        group = TaskGroup(name="reports")
        tm = _make_mock_task_manager(group)

        with pytest.raises(HTTPException) as exc_info:
            await delete_dynamic_task(tm, "reports", "ghost")
        assert exc_info.value.status_code == 404

    async def test_delete_unknown_group_returns_404(self):
        """Deleting from a non-existent group raises 404."""
        group = TaskGroup(name="reports")
        tm = _make_mock_task_manager(group)

        with pytest.raises(HTTPException) as exc_info:
            await delete_dynamic_task(tm, "nonexistent", "anything")
        assert exc_info.value.status_code == 404


class TestGetRegisteredFunctions:
    """Tests for the get_registered_functions service function."""

    def test_list_all(self):
        """Lists all registered functions across all groups."""
        g1 = TaskGroup(name="group1")
        g2 = TaskGroup(name="group2")

        @g1.register_function("func_a")
        async def fa():
            pass

        @g2.register_function("func_b")
        async def fb():
            pass

        tm = MagicMock()
        tm.task_groups = [g1, g2]

        result = get_registered_functions(tm)
        assert result.count == 2
        names = {f.function_name for f in result.functions}
        assert names == {"func_a", "func_b"}

    def test_filter_by_group(self):
        """Filtering by group returns only that group's functions."""
        g1 = TaskGroup(name="group1")
        g2 = TaskGroup(name="group2")

        @g1.register_function("func_a")
        async def fa():
            pass

        @g2.register_function("func_b")
        async def fb():
            pass

        tm = MagicMock()
        tm.task_groups = [g1, g2]

        result = get_registered_functions(tm, task_group_name="group1")
        assert result.count == 1
        assert result.functions[0].function_name == "func_a"

    def test_add_task_functions_appear_in_registry(self):
        """Functions registered via add_task(register=True) appear in the list."""
        group = TaskGroup(name="group1")

        @group.add_task("* * * * *", name="scheduled")
        async def scheduled():
            pass

        tm = MagicMock()
        tm.task_groups = [group]

        result = get_registered_functions(tm)
        assert result.count == 1
        assert result.functions[0].function_name == "scheduled"


# ---------------------------------------------------------------------------
# Startup loading tests
# ---------------------------------------------------------------------------


def _make_tm_for_loading(groups, redis_mock):
    """Helper to create a TaskManager instance for _load_dynamic_tasks testing."""
    with patch.object(TaskManager, "__init__", lambda *_args, **_kwargs: None):
        tm = TaskManager.__new__(TaskManager)
        tm._task_groups = groups
        tm._redis_client = redis_mock
        tm._config = MagicMock()
        tm._config.redis_key_prefix = "test"
    return tm


class TestLoadDynamicTasks:
    """Tests for TaskManager._load_dynamic_tasks on startup."""

    async def test_load_persisted_tasks(self):
        """Dynamic tasks are loaded from Redis Hash on startup."""
        group = TaskGroup(name="reports")

        @group.register_function("gen_report")
        async def gen_report():
            pass

        # Simulate persisted definition in Redis
        definition = {
            "task_group_name": "reports",
            "function_name": "gen_report",
            "cron_expression": "0 9 * * *",
            "kwargs": None,
            "name": "daily_report",
            "description": "Daily report task",
            "high_priority": False,
            "tags": None,
            "retry_backoff": None,
            "retry_backoff_max": None,
        }

        redis_mock = AsyncMock()
        redis_mock.hgetall.return_value = {
            b"reports:daily_report": json.dumps(definition).encode(),
        }

        tm = _make_tm_for_loading([group], redis_mock)
        await tm._load_dynamic_tasks()

        # Task was loaded
        assert len(group.tasks) == 1
        assert group.tasks[0].name == "daily_report"
        assert group.tasks[0].dynamic is True

    async def test_load_skips_missing_function(self):
        """Tasks referencing unregistered functions are skipped on load."""
        group = TaskGroup(name="reports")
        # No functions registered

        definition = {
            "task_group_name": "reports",
            "function_name": "removed_func",
            "cron_expression": "* * * * *",
            "name": "orphan_task",
        }

        redis_mock = AsyncMock()
        redis_mock.hgetall.return_value = {
            b"reports:orphan_task": json.dumps(definition).encode(),
        }

        tm = _make_tm_for_loading([group], redis_mock)
        await tm._load_dynamic_tasks()

        # No task loaded
        assert len(group.tasks) == 0

    async def test_load_skips_missing_group(self):
        """Tasks referencing non-existent groups are skipped on load."""
        group = TaskGroup(name="reports")

        definition = {
            "task_group_name": "nonexistent",
            "function_name": "func",
            "cron_expression": "* * * * *",
            "name": "orphan",
        }

        redis_mock = AsyncMock()
        redis_mock.hgetall.return_value = {
            b"nonexistent:orphan": json.dumps(definition).encode(),
        }

        tm = _make_tm_for_loading([group], redis_mock)
        await tm._load_dynamic_tasks()

        # No task loaded
        assert len(group.tasks) == 0
