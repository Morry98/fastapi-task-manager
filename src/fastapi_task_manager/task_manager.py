import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from fastapi_task_manager.config import Config
from fastapi_task_manager.runner import Runner
from fastapi_task_manager.task_group import TaskGroup

logger = logging.getLogger("fastapi.task-manager")


class TaskManager:
    def __init__(
        self,
        app: FastAPI,
        config: Config | None = None,
    ):
        self._config = config or Config()
        self._app = app
        self._running = False
        self._runner = Runner(
            redis_client=Redis(
                host=self._config.redis_host,
                port=self._config.redis_port,
                password=self._config.redis_password,
                db=self._config.redis_db,
            ),
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

    def add_task_group(
        self,
        task_group: TaskGroup,
    ):
        for task in task_group.tasks:
            self._runner.add_task(task)
