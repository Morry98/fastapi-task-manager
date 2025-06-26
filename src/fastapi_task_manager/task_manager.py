import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

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
            logger.info(f"Starting task '{name}' with expression '{expr}', function name '{func.__name__}'")
            # Create a task and add it to the running tasks list
            running_task = asyncio.create_task(run_task(func, expr), name=name)
            self._running_tasks.append(running_task)

        logger.info("Started TaskManager.")
        self._running = True
        # TODO

    async def stop(self) -> None:
        logger.info("Stopping TaskManager...")
        for task in self._running_tasks:
            if not task.done():
                logger.info(f"Cancelling task {task.get_name()}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"Task {task.get_name()} was cancelled.")
                except Exception as e:
                    logger.exception(f"Error stopping task {task.get_name()}: {e!r}")
        logger.info("Stopped TaskManager.")
        self._running = False

    def manager(self, expr: str, *, name=None, tags=None):
        """Decorator for creating task."""

        def wrapper(func: Callable):
            task = (func, expr, name, tags)
            self._tasks.append(task)
            logger.info(f"Registered task '{name}' with expression '{expr}', function name '{func.__name__}'")

            # If scheduler is already running, start this job immediately
            if self._running:
                logger.info(f"Scheduler already running, starting job '{name}' immediately")
                task = asyncio.create_task(run_task(func, expr), name=name)
                self._running_tasks.append(task)

            return func

        return wrapper


async def run_task(func, expr):
    next_run: datetime | None = None

    while True:
        if next_run is None or datetime.now(UTC) >= next_run:
            try:
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    await asyncio.to_thread(func)
            except Exception as e:
                logger.exception(f"Error running task {func.__name__}: {e!r}")
            next_run = next_fire(expr)
        await asyncio.sleep(1)
