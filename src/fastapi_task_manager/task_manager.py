import logging
from contextlib import asynccontextmanager
from typing import Any

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
        self._running = True
        # TODO

    async def stop(self) -> None:
        logger.info("Stopping TaskManager...")
        self._running = False
        # TODO
