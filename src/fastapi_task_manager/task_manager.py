import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from fastapi_task_manager.config import Config
from fastapi_task_manager.runner import Runner
from fastapi_task_manager.schema.task import Task

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
        self._running = False
        self._runner = Runner(
            redis_client=redis_client,
            concurrent_tasks=self._config.concurrent_tasks,
        )

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
        if self._running:
            logger.warning("TaskManager is already running.")
            return
        self._running = True
        logger.info("Starting TaskManager...")
        await self._runner.start()
        logger.info("Started TaskManager.")

    async def stop(self) -> None:
        if not self._running:
            logger.warning("TaskManager is not running.")
            return
        self._running = False
        logger.info("Stopping TaskManager...")
        await self._runner.stop()
        logger.info("Stopped TaskManager.")

    def add_task(
        self,
        expr: str,
        tags: list[str] | None = None,
        name: str | None = None,
        description: str | None = None,
        high_priority: bool = False,
    ):
        """Decorator for creating task."""

        def wrapper(func: Callable):
            task = Task(
                function=func,
                expression=expr,
                name=name or func.__name__,
                description=description,
                tags=tags,
                high_priority=high_priority,
            )
            self._runner.add_task(task)

            return func

        return wrapper
