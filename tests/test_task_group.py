"""Tests for TaskGroup class."""

import pytest

from fastapi_task_manager.task_group import TaskGroup


class TestTaskGroupInit:
    """Tests for TaskGroup initialization."""

    def test_basic_init(self):
        group = TaskGroup(name="my_group")
        assert group.name == "my_group"
        assert group.tags == []
        assert group.tasks == []
        assert group.function_registry == {}

    def test_init_with_tags(self):
        group = TaskGroup(name="g", tags=["a", "b"])
        assert group.tags == ["a", "b"]

    def test_tags_returns_copy(self):
        """Modifying returned tags should not affect the group."""
        group = TaskGroup(name="g", tags=["a"])
        tags = group.tags
        tags.append("b")
        assert group.tags == ["a"]

    def test_tasks_returns_copy(self):
        group = TaskGroup(name="g")
        tasks = group.tasks
        assert tasks == []
        # Should be a different list instance
        assert tasks is not group._tasks


class TestAddTask:
    """Tests for the add_task decorator."""

    def test_single_expression(self):
        group = TaskGroup(name="g")

        @group.add_task("*/5 * * * *")
        async def my_task():
            pass

        assert len(group.tasks) == 1
        assert group.tasks[0].expression == "*/5 * * * *"
        assert group.tasks[0].dynamic is False

    def test_multiple_expressions_as_list(self):
        group = TaskGroup(name="g")

        @group.add_task(["*/5 * * * *", "*/10 * * * *"])
        async def my_task():
            pass

        assert len(group.tasks) == 2

    def test_multiple_expressions_with_kwargs(self):
        group = TaskGroup(name="g")

        @group.add_task(
            ["*/5 * * * *", "*/10 * * * *"],
            kwargs=[{"region": "us"}, {"region": "eu"}],
        )
        async def my_task(region):
            pass

        assert len(group.tasks) == 2
        kwargs_list = [t.kwargs for t in group.tasks]
        assert {"region": "us"} in kwargs_list
        assert {"region": "eu"} in kwargs_list

    def test_mismatched_expr_kwargs_raises(self):
        group = TaskGroup(name="g")

        with pytest.raises(TypeError, match="same length"):

            @group.add_task(
                ["*/5 * * * *", "*/10 * * * *"],
                kwargs=[{"a": 1}],
            )
            async def my_task(a):
                pass

    def test_duplicate_task_name_raises(self):
        group = TaskGroup(name="g")

        @group.add_task("*/5 * * * *", name="dup_task")
        async def task_a():
            pass

        with pytest.raises(RuntimeError, match="already exists"):

            @group.add_task("*/5 * * * *", name="dup_task")
            async def task_b():
                pass

    def test_high_priority_flag(self):
        group = TaskGroup(name="g")

        @group.add_task("* * * * *", high_priority=True)
        async def hp_task():
            pass

        assert group.tasks[0].high_priority is True

    def test_description_and_tags(self):
        group = TaskGroup(name="g")

        @group.add_task("* * * * *", description="Does stuff", tags=["important"])
        async def tagged_task():
            pass

        assert group.tasks[0].description == "Does stuff"

    def test_retry_backoff_overrides(self):
        group = TaskGroup(name="g")

        @group.add_task("* * * * *", retry_backoff=5.0, retry_backoff_max=120.0)
        async def retried_task():
            pass

        assert group.tasks[0].retry_backoff == 5.0
        assert group.tasks[0].retry_backoff_max == 120.0

    def test_register_true_adds_to_registry(self):
        group = TaskGroup(name="g")

        @group.add_task("* * * * *", name="fn")
        async def my_fn():
            pass

        assert "fn" in group.function_registry

    def test_register_false_skips_registry(self):
        group = TaskGroup(name="g")

        @group.add_task("* * * * *", name="fn2", register=False)
        async def my_fn():
            pass

        assert "fn2" not in group.function_registry


class TestRegisterFunction:
    """Tests for the register_function decorator."""

    def test_basic_registration(self):
        group = TaskGroup(name="g")

        @group.register_function("my_func")
        async def func():
            pass

        assert "my_func" in group.function_registry
        assert group.function_registry["my_func"] is func

    def test_default_name_from_function(self):
        group = TaskGroup(name="g")

        @group.register_function()
        async def auto_named():
            pass

        assert "auto_named" in group.function_registry

    def test_duplicate_registration_raises(self):
        group = TaskGroup(name="g")

        @group.register_function("dup")
        async def f1():
            pass

        with pytest.raises(RuntimeError, match="already registered"):

            @group.register_function("dup")
            async def f2():
                pass

    def test_function_registry_returns_copy(self):
        group = TaskGroup(name="g")

        @group.register_function("f")
        async def func():
            pass

        registry = group.function_registry
        registry["new"] = lambda: None
        assert "new" not in group.function_registry


class TestDynamicTask:
    """Tests for add_dynamic_task and remove_dynamic_task."""

    def _make_group_with_func(self):
        group = TaskGroup(name="test")

        @group.register_function("my_func")
        async def my_func():
            pass

        return group

    def test_add_dynamic_task(self):
        group = self._make_group_with_func()
        task = group.add_dynamic_task("my_func", "* * * * *")
        assert task.dynamic is True
        assert task.function_name == "my_func"
        assert len(group.tasks) == 1

    def test_add_dynamic_task_with_custom_name(self):
        group = self._make_group_with_func()
        task = group.add_dynamic_task("my_func", "* * * * *", name="custom_name")
        assert task.name == "custom_name"

    def test_add_dynamic_task_unregistered_function_raises(self):
        group = TaskGroup(name="test")
        with pytest.raises(RuntimeError, match="not registered"):
            group.add_dynamic_task("nonexistent", "* * * * *")

    def test_add_dynamic_task_duplicate_name_raises(self):
        group = self._make_group_with_func()
        group.add_dynamic_task("my_func", "* * * * *", name="dup")
        with pytest.raises(RuntimeError, match="already exists"):
            group.add_dynamic_task("my_func", "*/5 * * * *", name="dup")

    def test_remove_dynamic_task(self):
        group = self._make_group_with_func()
        group.add_dynamic_task("my_func", "* * * * *", name="to_remove")
        removed = group.remove_dynamic_task("to_remove")
        assert removed.name == "to_remove"
        assert len(group.tasks) == 0

    def test_remove_nonexistent_task_raises(self):
        group = self._make_group_with_func()
        with pytest.raises(RuntimeError, match="not found"):
            group.remove_dynamic_task("nope")

    def test_remove_static_task_raises(self):
        group = TaskGroup(name="test")

        @group.add_task("* * * * *", name="static")
        async def static_task():
            pass

        with pytest.raises(RuntimeError, match="static"):
            group.remove_dynamic_task(group.tasks[0].name)
