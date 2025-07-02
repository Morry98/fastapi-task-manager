import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from cronexpr import next_fire
from redis.asyncio import Redis

from fastapi_task_manager.force_acquire_semaphore import ForceAcquireSemaphore
from fastapi_task_manager.schema.task import Task

logger = logging.getLogger("fastapi.task-manager")


class Runner:
    def __init__(
        self,
        redis_client: Redis,
        concurrent_tasks: int,
    ):
        self._uuid: str = str(uuid4().int)
        self._redis_client = redis_client
        self._running_thread: asyncio.Task | None = None
        self._tasks: list[Task] = []
        self._running_tasks: dict[Task, asyncio.Task] = {}
        self._semaphore = ForceAcquireSemaphore(concurrent_tasks)

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
        for task in self._tasks:
            if task in self._running_tasks:
                await stop_thread(self._running_tasks[task])
                self._running_tasks.pop(task, None)
        await stop_thread(self._running_thread)
        self._running_thread = None
        logger.info("Stopped TaskManager.")

    def add_task(self, task: Task) -> None:
        for t in self._tasks:
            if t.name == task.name:
                msg = f"Task with name {task.name} already exists."
                raise RuntimeError(msg)
        self._tasks.append(task)

    async def _run(self):
        while True:
            await asyncio.sleep(0.1)
            try:
                for task in self._tasks:
                    if task in self._running_tasks:
                        if not self._running_tasks[task].done():
                            continue
                        self._running_tasks[task].result()
                        # If the task is done, remove it from the running tasks list
                        self._running_tasks.pop(task, None)

                    next_run = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
                    if await self._redis_client.exists(task.name + "_next_run"):
                        next_run_b = await self._redis_client.get(task.name + "_next_run")
                        if next_run_b is None:
                            return
                        next_run = datetime.fromtimestamp(float(next_run_b.decode("utf-8")), tz=timezone.utc)
                    if next_run <= datetime.now(timezone.utc):
                        self._running_tasks[task] = asyncio.create_task(self._queue_task(task), name=task.name)
            except asyncio.CancelledError:
                logger.info("Runner task was cancelled.")
                return
            except Exception:
                logger.exception("Error in Runner task loop.")
                continue

    async def _queue_task(self, task: Task):
        if task.high_priority:
            async with self._semaphore.force_acquire():
                await self._run_task(task)
        else:
            async with self._semaphore:
                await self._run_task(task)

    async def _run_task(self, task: Task) -> None:
        try:
            if await self._redis_client.exists(task.name + "_next_run"):
                redis_next_run_b = await self._redis_client.get(task.name + "_next_run")
                if redis_next_run_b is None:
                    return
                redis_next_run = datetime.fromtimestamp(float(redis_next_run_b.decode("utf-8")), tz=timezone.utc)
                if redis_next_run > datetime.now(timezone.utc):
                    return

            redis_uuid_exists = await self._redis_client.exists(task.name + "_runner_uuid")
            if not redis_uuid_exists:
                await self._redis_client.set(task.name + "_runner_uuid", self._uuid, ex=15)
                # Wait a bit to ensure the UUID is set and not overwritten
                await asyncio.sleep(0.2)
            redis_uuid_b = await self._redis_client.get(task.name + "_runner_uuid")
            if redis_uuid_b is None:
                return
            if redis_uuid_b.decode("utf-8") != self._uuid:
                return

            next_run = next_fire(task.expression)
            await self._redis_client.set(
                task.name + "_next_run",
                next_run.timestamp(),
                ex=max(int((next_run - datetime.now(timezone.utc)).total_seconds()) * 2, 15),
            )

            thread = asyncio.create_task(run_function(task.function))
            while not thread.done():
                await self._redis_client.set(task.name + "_runner_uuid", self._uuid, ex=5)
                await asyncio.sleep(0.1)
            await self._redis_client.delete(task.name + "_runner_uuid")

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
