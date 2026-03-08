"""Tests for Pydantic schema models."""

from datetime import datetime, timezone

from fastapi_task_manager.schema.health import ConfigResponse, HealthResponse
from fastapi_task_manager.schema.task import (
    AffectedTask,
    CreateDynamicTaskRequest,
    DynamicTaskResponse,
    RegisteredFunctionInfo,
    RegisteredFunctionsResponse,
    Task,
    TaskActionResponse,
    TaskBase,
    TaskDetailed,
    TaskRun,
)
from fastapi_task_manager.schema.task_group import TaskGroup as TaskGroupSchema


class TestTaskBase:
    def test_minimal_creation(self):
        tb = TaskBase(expression="* * * * *", name="test")
        assert tb.expression == "* * * * *"
        assert tb.name == "test"
        assert tb.high_priority is False
        assert tb.dynamic is False
        assert tb.tags is None
        assert tb.retry_backoff is None


class TestTask:
    def test_task_with_function(self):
        async def my_func():
            pass

        task = Task(function=my_func, expression="*/5 * * * *", name="my_task")
        assert task.function is my_func
        assert task.kwargs is None
        assert task.function_name is None

    def test_task_hash(self):
        async def f1():
            pass

        async def f2():
            pass

        t1 = Task(function=f1, expression="* * * * *", name="t1")
        t2 = Task(function=f2, expression="* * * * *", name="t2")
        # Different names should produce different hashes
        assert hash(t1) != hash(t2)

    def test_task_with_kwargs(self):
        async def func(x=1):
            pass

        task = Task(function=func, expression="* * * * *", name="t", kwargs={"x": 42})
        assert task.kwargs == {"x": 42}


class TestTaskRun:
    def test_creation(self):
        run = TaskRun(
            run_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            durations_second=1.5,
        )
        assert run.durations_second == 1.5


class TestTaskDetailed:
    def test_creation_with_defaults(self):
        td = TaskDetailed(
            expression="* * * * *",
            name="t1",
            task_group_name="g1",
            next_run=datetime(2024, 1, 1, tzinfo=timezone.utc),
            is_active=True,
            runs=[],
        )
        assert td.is_running is False
        assert td.retry_after is None
        assert td.retry_delay is None


class TestAffectedTask:
    def test_creation(self):
        at = AffectedTask(task_group="g", task="t")
        assert at.task_group == "g"
        assert at.task == "t"


class TestTaskActionResponse:
    def test_creation(self):
        resp = TaskActionResponse(
            affected_tasks=[AffectedTask(task_group="g", task="t")],
            count=1,
        )
        assert resp.count == 1


class TestDynamicTaskSchemas:
    def test_create_request_defaults(self):
        req = CreateDynamicTaskRequest(
            task_group_name="g",
            function_name="f",
            cron_expression="* * * * *",
        )
        assert req.kwargs is None
        assert req.high_priority is False
        assert req.tags is None

    def test_dynamic_task_response(self):
        resp = DynamicTaskResponse(
            task_group_name="g",
            task_name="t",
            function_name="f",
            cron_expression="* * * * *",
        )
        assert resp.dynamic is True

    def test_registered_functions_response(self):
        resp = RegisteredFunctionsResponse(
            functions=[
                RegisteredFunctionInfo(task_group_name="g", function_name="f"),
            ],
            count=1,
        )
        assert resp.count == 1


class TestHealthResponse:
    def test_creation_with_defaults(self):
        hr = HealthResponse(status="healthy", redis_connected=True)
        assert hr.worker_id is None
        assert hr.is_leader is None

    def test_creation_with_worker_info(self):
        hr = HealthResponse(
            status="healthy",
            redis_connected=True,
            worker_id="w1",
            worker_started_at="2024-01-01T00:00:00",
            is_leader=True,
        )
        assert hr.worker_id == "w1"
        assert hr.is_leader is True


class TestConfigResponse:
    def test_creation(self):
        cr = ConfigResponse(
            redis_key_prefix="test",
            concurrent_tasks=2,
            statistics_history_runs=30,
            statistics_redis_expiration=432000,
            poll_interval=0.1,
            worker_service_name="svc",
            stream_max_len=10000,
            stream_block_ms=1000,
            leader_heartbeat_interval=3.0,
            leader_retry_interval=5.0,
            reconciliation_interval=30,
            retry_backoff=1.0,
            retry_backoff_max=60.0,
            retry_backoff_multiplier=2.0,
            running_heartbeat_interval=3.0,
        )
        assert cr.redis_key_prefix == "test"


class TestTaskGroupSchema:
    def test_creation(self):
        tg = TaskGroupSchema(name="g1", tags=["a"], task_count=5)
        assert tg.name == "g1"
        assert tg.task_count == 5
