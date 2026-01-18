import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from croniter import croniter
from redis.asyncio import Redis

from fastapi_task_manager import TaskGroup
from fastapi_task_manager.force_acquire_semaphore import ForceAcquireSemaphore
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task
from fastapi_task_manager.schema.worker_identity import WorkerIdentity
from fastapi_task_manager.statistics import StatisticsStorage

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager

logger = logging.getLogger("fastapi.task-manager")


class Runner:
    def __init__(
        self,
        redis_client: Redis,
        concurrent_tasks: int,
        task_manager: "TaskManager",
    ):
        # Use WorkerIdentity for traceable worker identification
        self._worker = WorkerIdentity(task_manager.config.worker_service_name)
        self._uuid = self._worker.redis_safe_id
        # Initialize the key builder for centralized key construction
        self._key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)
        self._redis_client = redis_client
        self._running_thread: asyncio.Task | None = None
        self._running_tasks: dict[Task, asyncio.Task] = {}
        self._semaphore = ForceAcquireSemaphore(concurrent_tasks)
        self._task_manager = task_manager
        # Initialize statistics storage with Redis Lists for atomic operations
        self._statistics = StatisticsStorage(
            redis_client=redis_client,
            max_entries=task_manager.config.statistics_history_runs,
            ttl_seconds=task_manager.config.statistics_redis_expiration,
        )

    async def start(self) -> None:
        if self._running_thread:
            msg = "Runner is already running."
            logger.warning(msg)
            return
        try:
            pong = await self._redis_client.ping()  # ty: ignore[invalid-await]
        except Exception as e:
            msg = f"Redis ping failed: {e!r}"
            raise ConnectionError(msg) from e
        if not pong:
            msg = "Redis ping returned falsy response"
            raise ConnectionError(msg)

        self._running_thread = asyncio.create_task(self._run(), name="Runner")
        # Log the runner startup with worker identity for traceability
        logger.info("Runner started successfully. Worker: %s", self._worker)

    async def stop(self) -> None:
        if not self._running_thread:
            msg = "Runner is not running."
            logger.warning(msg)
            return
        for _task, asyncio_task in self._running_tasks.items():
            await stop_thread(asyncio_task)
        self._running_tasks.clear()
        await stop_thread(self._running_thread)
        self._running_thread = None
        logger.info("Stopped TaskManager.")

    async def _run(self):
        while True:
            await asyncio.sleep(self._task_manager.config.poll_interval)
            try:
                for task_group in self._task_manager.task_groups:
                    for task in task_group.tasks:
                        if task in self._running_tasks:
                            if not self._running_tasks[task].done():
                                continue
                            self._running_tasks[task].result()
                            # If the task is done, remove it from the running tasks list
                            self._running_tasks.pop(task, None)

                        # Use RedisKeyBuilder for centralized key construction
                        keys = self._key_builder.get_task_keys(task_group.name, task.name)
                        next_run = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
                        next_run_b = await self._redis_client.get(keys.next_run)
                        if next_run_b is not None:
                            next_run = datetime.fromtimestamp(float(next_run_b.decode("utf-8")), tz=timezone.utc)
                        if next_run <= datetime.now(timezone.utc):
                            self._running_tasks[task] = asyncio.create_task(
                                self._queue_task(task=task, task_group=task_group),
                                name=task_group.name + "_" + task.name,
                            )
            except asyncio.CancelledError:
                logger.info("Runner task was cancelled.")
                return
            except Exception:
                logger.exception("Error in Runner task loop.")
                continue

    async def _queue_task(self, task: Task, task_group: TaskGroup):
        if task.high_priority:
            async with self._semaphore.force_acquire():
                await self._run_task(task=task, task_group=task_group)
        else:
            async with self._semaphore:
                await self._run_task(task=task, task_group=task_group)

    async def _run_task(self, task_group: TaskGroup, task: Task) -> None:
        try:
            keys = self._key_builder.get_task_keys(task_group.name, task.name)

            redis_next_run_b = await self._redis_client.get(keys.next_run)
            if redis_next_run_b is not None:
                redis_next_run = datetime.fromtimestamp(float(redis_next_run_b.decode("utf-8")), tz=timezone.utc)
                if redis_next_run > datetime.now(timezone.utc):
                    return

            lock_acquired = await self._redis_client.set(
                keys.runner_uuid,
                self._uuid,
                nx=True,
                ex=self._task_manager.config.initial_lock_ttl,
            )
            if not lock_acquired:
                # Lock already exists, check if we are the owner
                redis_uuid_b = await self._redis_client.get(keys.runner_uuid)
                if redis_uuid_b is None or redis_uuid_b.decode("utf-8") != self._uuid:
                    # Another runner owns the lock, exit gracefully
                    return

            local_date = datetime.now(timezone.utc)
            next_run = croniter(task.expression, local_date).get_next(datetime)
            # Calculate expiration time, ensuring it's at least initial_lock_ttl seconds
            next_run_ttl = int((next_run - datetime.now(timezone.utc)).total_seconds()) * 2
            expiration = max(next_run_ttl, self._task_manager.config.initial_lock_ttl)
            await self._redis_client.set(keys.next_run, next_run.timestamp(), ex=expiration)

            disabled_b = await self._redis_client.get(keys.disabled)
            if disabled_b is not None:
                # Task is disabled, update TTL and exit
                await self._redis_client.set(
                    keys.disabled,
                    "1",
                    ex=self._task_manager.config.statistics_redis_expiration,
                )
                return

            start = time.monotonic_ns()
            thread = asyncio.create_task(
                run_function(
                    function=task.function,
                    kwargs=task.kwargs,
                ),
            )

            last_renewal_time = time.monotonic()
            while not thread.done():
                current_time = time.monotonic()
                if current_time - last_renewal_time >= self._task_manager.config.lock_renewal_interval:
                    await self._redis_client.set(
                        keys.runner_uuid,
                        self._uuid,
                        ex=self._task_manager.config.running_lock_ttl,
                    )
                    last_renewal_time = current_time
                await asyncio.sleep(self._task_manager.config.poll_interval)
            end = time.monotonic_ns()

            # Record execution statistics using Redis Lists with atomic pipeline operations
            await self._statistics.record_execution(
                runs_key=keys.runs,
                durations_key=keys.durations_second,
                timestamp=datetime.now(timezone.utc).timestamp(),
                duration_seconds=(end - start) / 1e9,
            )
            # Delete the lock key after task completion
            await self._redis_client.delete(keys.runner_uuid)

        except asyncio.CancelledError:
            msg = f"Task {task.name} was cancelled."
            logger.info(msg)
        except Exception:
            logger.exception("Failed to run task.")


async def stop_thread(running_task: asyncio.Task) -> None:
    if not running_task.done():
        running_task.cancel()
        try:
            await running_task
        except asyncio.CancelledError:
            return
        except Exception:
            msg = "Error stopping Runner"
            logger.exception(msg)


async def run_function(
    function: Callable,
    kwargs: dict | None = None,
):
    try:
        if asyncio.iscoroutinefunction(function):
            await function(**(kwargs or {}))
        else:
            await asyncio.to_thread(function, **(kwargs or {}))
    except Exception:
        logger.exception("Error running function.")
