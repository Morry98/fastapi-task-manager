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
            if task.running_thread:
                await stop_thread(task.running_thread)
                task.running_thread = None
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
                    if task.running_thread is not None:
                        if not task.running_thread.done():
                            continue
                        # If the task is done, remove it from the running tasks list
                        task.running_thread = None
                    elif task.next_run <= datetime.now(timezone.utc):
                        task.next_run = next_fire(task.expression)
                        task.running_thread = asyncio.create_task(self._queue_task(task), name=task.name)
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
            redis_key_exists = await self._redis_client.exists(task.name + "_valid")
            if redis_key_exists:
                return

            redis_uuid_exists = await self._redis_client.exists(task.name + "_runner_uuid")
            if not redis_uuid_exists:
                await self._redis_client.set(task.name + "_runner_uuid", self._uuid, ex=5)
                await asyncio.sleep(0.2)
            redis_uuid_b = await self._redis_client.get(task.name + "_runner_uuid")
            if redis_uuid_b is None:
                return
            if redis_uuid_b.decode("utf-8") != self._uuid:
                return

            thread = asyncio.create_task(run_function(task.function))
            while not thread.done():
                await self._redis_client.set(task.name + "_runner_uuid", self._uuid, ex=1)
                await asyncio.sleep(0.1)

            task.next_run = next_fire(task.expression)
            ex = int((task.next_run - datetime.now(timezone.utc)).total_seconds())
            if ex <= 0:
                return
            await self._redis_client.set(
                task.name + "_valid",
                1,
                ex=ex,
            )
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
