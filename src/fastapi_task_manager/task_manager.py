import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from cronexpr import next_fire
from fastapi import FastAPI
from redis.asyncio import Redis

from fastapi_task_manager.config import Config

logger = logging.getLogger("fastapi.task-manager")


class TaskManager:
    def __init__(
        self,
        app: FastAPI,
        redis_client: Redis,
        config: Config | None = None,
    ):
        self._uuid: str = str(uuid4().int)
        self._config = config or Config()
        self._app = app
        self._redis_client = redis_client
        self._running = False
        self._tasks: list[Any] = []  # TODO Define a proper type for tasks
        self._running_tasks: list[asyncio.Task] = []  # Keep track of running tasks

        logger.setLevel(self._config.level.upper().strip())

        self.append_to_app_lifecycle(app)

    def append_to_app_lifecycle(self, app: FastAPI) -> None:
        """Automatically start/stop with app lifecycle."""

        # Check if app already has a lifespan
        existing_lifespan = getattr(app.router, "lifespan_context", None)

        @asynccontextmanager
        async def lifespan(app):
            await self.start()
            try:
                if existing_lifespan:
                    # If there's an existing lifespan, run it
                    async with existing_lifespan(app):
                        yield
                else:
                    yield
            finally:
                await self.stop()

        # Set the new lifespan
        app.router.lifespan_context = lifespan

    async def start(self) -> None:
        logger.info("Starting TaskManager...")
        try:
            pong = await self._redis_client.ping()
        except Exception as e:
            msg = f"Redis ping failed: {e!r}"
            raise ConnectionError(msg) from e
        if not pong:
            msg = "Redis ping returned falsy response"
            raise ConnectionError(msg)

        for task in self._tasks:
            func, expr, name, tags = task
            msg = f"Registering task '{name}' with expression '{expr}', function name '{func.__name__}'"
            logger.info(msg)
            # Create a task and add it to the running tasks list
            running_task = asyncio.create_task(self._run_task(func, expr), name=name)
            self._running_tasks.append(running_task)

        logger.info("Started TaskManager.")
        self._running = True
        # TODO

    async def stop(self) -> None:
        logger.info("Stopping TaskManager...")
        for task in self._running_tasks:
            if not task.done():
                msg = f"Cancelling task {task.get_name()}"
                logger.info(msg)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    msg = f"Task {task.get_name()} was cancelled."
                    logger.info(msg)
                except Exception:
                    msg = f"Error stopping task {task.get_name()}"
                    logger.exception(msg)
        logger.info("Stopped TaskManager.")
        self._running = False

    def manager(self, expr: str, *, name=None, tags=None):
        """Decorator for creating task."""

        def wrapper(func: Callable):
            task = (func, expr, name, tags)
            self._tasks.append(task)
            msg = f"Registered task '{name}' with expression '{expr}', function name '{func.__name__}'"
            logger.info(msg)

            # If scheduler is already running, start this job immediately
            if self._running:
                msg = f"Scheduler already running, starting job '{name}' immediately"
                logger.info(msg)
                running_task = asyncio.create_task(self._run_task(func, expr), name=name)
                self._running_tasks.append(running_task)

            return func

        return wrapper

    async def _run_task(self, func, expr):  # noqa: PLR0912
        next_run: datetime = datetime.min

        while True:
            if datetime.now(UTC) >= next_run:
                next_run = next_fire(expr)
                try:
                    redis_uuid_exists = await self._redis_client.exists(func.__name__ + "_runner_uuid")
                    if not redis_uuid_exists:
                        await self._redis_client.set(func.__name__ + "_runner_uuid", self._uuid, ex=2)
                        await asyncio.sleep(0.2)
                    redis_uuid_b = await self._redis_client.get(func.__name__ + "_runner_uuid")
                    if redis_uuid_b is None:
                        continue
                    redis_uuid = redis_uuid_b.decode("utf-8")
                    if redis_uuid != self._uuid:
                        continue
                except Exception:
                    msg = f"Error checking Redis UUID for task {func.__name__}"
                    logger.exception(msg)
                    continue
                try:
                    redis_key_exists = await self._redis_client.exists(func.__name__ + "_valid")
                    if redis_key_exists:
                        continue
                    ex = int((next_run - datetime.now(UTC)).total_seconds())
                    if ex <= 0:
                        continue
                    await self._redis_client.set(
                        func.__name__ + "_valid",
                        1,
                        ex=ex,
                    )
                    if asyncio.iscoroutinefunction(func):
                        await func()
                    else:
                        await asyncio.to_thread(func)
                except Exception:
                    msg = f"Error running task {func.__name__}"
                    logger.exception(msg)
                finally:
                    # Clean up the UUID in Redis after running the task
                    try:
                        await self._redis_client.delete(func.__name__ + "_runner_uuid")
                    except Exception:
                        msg = f"Error deleting Redis UUID for task {func.__name__}"
                        logger.exception(msg)
            await asyncio.sleep(1)
