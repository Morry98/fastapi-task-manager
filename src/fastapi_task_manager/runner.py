import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from cronexpr import next_fire
from redis.asyncio import Redis

from fastapi_task_manager import TaskGroup
from fastapi_task_manager.force_acquire_semaphore import ForceAcquireSemaphore
from fastapi_task_manager.schema.task import Task

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
        self._uuid: str = str(uuid4().int)
        self._redis_client = redis_client
        self._running_thread: asyncio.Task | None = None
        self._running_tasks: dict[Task, asyncio.Task] = {}
        self._semaphore = ForceAcquireSemaphore(concurrent_tasks)
        self._task_manager = task_manager

    async def start(self) -> None:
        if self._running_thread:
            msg = "Runner is already running."
            logger.warning(msg)
            return
        try:
            pong = await self._redis_client.ping()
        except Exception as e:
            msg = f"Redis ping failed: {e!r}"
            raise ConnectionError(msg) from e
        if not pong:
            msg = "Redis ping returned falsy response"
            raise ConnectionError(msg)

        self._running_thread = asyncio.create_task(self._run(), name="Runner")
        logger.info("Runner started successfully.")

    async def stop(self) -> None:
        if not self._running_thread:
            msg = "Runner is not running."
            logger.warning(msg)
            return
        for _task, asyncio_task in self._running_tasks:
            await stop_thread(asyncio_task)
        self._running_tasks.clear()
        await stop_thread(self._running_thread)
        self._running_thread = None
        logger.info("Stopped TaskManager.")

    async def _run(self):
        while True:
            await asyncio.sleep(0.1)
            try:
                for task_group in self._task_manager.task_groups:
                    for task in task_group.tasks:
                        if task in self._running_tasks:
                            if not self._running_tasks[task].done():
                                continue
                            self._running_tasks[task].result()
                            # If the task is done, remove it from the running tasks list
                            self._running_tasks.pop(task, None)

                        next_run = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
                        if await self._redis_client.exists(task_group.name + "_" + task.name + "_next_run"):
                            next_run_b = await self._redis_client.get(task_group.name + "_" + task.name + "_next_run")
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

    async def _run_task(self, task_group: TaskGroup, task: Task) -> None:  # noqa: PLR0912, C901  # TODO Reduce complexity
        try:
            if await self._redis_client.exists(task_group.name + "_" + task.name + "_next_run"):
                redis_next_run_b = await self._redis_client.get(task_group.name + "_" + task.name + "_next_run")
                if redis_next_run_b is None:
                    return
                redis_next_run = datetime.fromtimestamp(float(redis_next_run_b.decode("utf-8")), tz=timezone.utc)
                if redis_next_run > datetime.now(timezone.utc):
                    return

            redis_uuid_exists = await self._redis_client.exists(task_group.name + "_" + task.name + "_runner_uuid")
            if not redis_uuid_exists:
                await self._redis_client.set(task_group.name + "_" + task.name + "_runner_uuid", self._uuid, ex=15)
                # Wait a bit to ensure the UUID is set and not overwritten
                await asyncio.sleep(0.2)
            redis_uuid_b = await self._redis_client.get(task_group.name + "_" + task.name + "_runner_uuid")
            if redis_uuid_b is None:
                return
            if redis_uuid_b.decode("utf-8") != self._uuid:
                return

            next_run = next_fire(task.expression)
            await self._redis_client.set(
                task_group.name + "_" + task.name + "_next_run",
                next_run.timestamp(),
                # using max to ensure that the expiration isn't lower than 15 seconds
                # in this way we avoid potential issues
                ex=max(int((next_run - datetime.now(timezone.utc)).total_seconds()) * 2, 15),
            )

            if await self._redis_client.exists(task_group.name + "_" + task.name + "_disabled"):
                # Set the key in order to update the ttl
                await self._redis_client.set(
                    task_group.name + "_" + task.name + "_disabled",
                    "1",
                    ex=self._task_manager.config.statistics_redis_expiration,
                )
                return

            start = time.monotonic_ns()
            thread = asyncio.create_task(run_function(task.function))
            while not thread.done():
                await self._redis_client.set(task_group.name + "_" + task.name + "_runner_uuid", self._uuid, ex=5)
                await asyncio.sleep(0.1)
            end = time.monotonic_ns()
            runs = []  # TODO Evaluate redis linked lists
            if await self._redis_client.exists(task_group.name + "_" + task.name + "_runs"):
                runs_b = await self._redis_client.get(task_group.name + "_" + task.name + "_runs")
                if runs_b is not None:
                    runs = runs_b.decode("utf-8").split("\n")
            if len(runs) == 30:  # noqa: PLR2004  # TODO Configurable
                runs.pop(0)
            runs.append(str(datetime.now(timezone.utc).timestamp()))
            await self._redis_client.set(
                task_group.name + "_" + task.name + "_runs",
                "\n".join(runs),
                ex=self._task_manager.config.statistics_redis_expiration,
            )
            durations_second = []  # TODO Evaluate redis linked lists
            if await self._redis_client.exists(task_group.name + "_" + task.name + "_durations_second"):
                durations_second_b = await self._redis_client.get(
                    task_group.name + "_" + task.name + "_durations_second",
                )
                if durations_second_b is not None:
                    durations_second = durations_second_b.decode("utf-8").split("\n")
            if len(durations_second) == 30:  # noqa: PLR2004  # TODO Configurable
                durations_second.pop(0)
            durations_second.append(str((end - start) / 1e9))
            await self._redis_client.set(
                task_group.name + "_" + task.name + "_duration_seconds",
                "\n".join(durations_second),
                ex=self._task_manager.config.statistics_redis_expiration,
            )
            await self._redis_client.delete(task_group.name + "_" + task.name + "_runner_uuid")

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


async def run_function(function: Callable):
    try:
        if asyncio.iscoroutinefunction(function):
            await function()
        else:
            await asyncio.to_thread(function)
    except Exception:
        logger.exception("Error running function.")
