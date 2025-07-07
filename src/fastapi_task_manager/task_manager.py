import functools
import inspect
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, FastAPI
from redis.asyncio import Redis

from fastapi_task_manager.config import Config
from fastapi_task_manager.runner import Runner
from fastapi_task_manager.schema.task import TaskBase
from fastapi_task_manager.schema.task_group import TaskGroup as TaskGroupSchema
from fastapi_task_manager.task_group import TaskGroup
from fastapi_task_manager.task_router_services import disable_task, enable_task, get_task_groups, get_tasks

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("fastapi.task-manager")


class TaskManager:
    def __init__(
        self,
        app: FastAPI,
        config: Config | None = None,
    ):
        self._config = config or Config()
        self._app = app
        self._runner: Runner | None = None
        self._task_groups: list[TaskGroup] = []

        logger.setLevel(self._config.level.upper().strip())

        self.append_to_app_lifecycle(app)

    @property
    def task_groups(self) -> list[TaskGroup]:
        return self._task_groups.copy()

    @property
    def config(self) -> Config:
        return self._config

    def add_manager_paths_to_router(
        self,
        router: APIRouter,
    ):
        func: Callable
        for func, router_path in {
            (
                cast("Callable[..., Any]", get_task_groups),
                router.get(
                    "/task_groups",
                    response_model_by_alias=True,
                    response_model=list[TaskGroupSchema],
                    description="Get task groups",
                    name="Get task groups",
                ),
            ),
            (
                cast("Callable[..., Any]", get_tasks),
                router.get(
                    "/tasks",
                    response_model_by_alias=True,
                    response_model=list[TaskBase],
                    description="Get tasks",
                    name="Get tasks",
                ),
            ),
            (
                cast("Callable[..., Any]", disable_task),
                router.post(
                    "/disable_tasks",
                    response_model_by_alias=True,
                    description="Disable tasks",
                    name="Disable tasks",
                ),
            ),
            (
                cast("Callable[..., Any]", enable_task),
                router.post(
                    "/enable_tasks",
                    response_model_by_alias=True,
                    description="Enable tasks",
                    name="Enable tasks",
                ),
            ),
        }:
            partial_func = functools.partial(
                func,
                task_manager=self,
            )

            sig = inspect.signature(partial_func)
            sig = sig.replace(
                parameters=[param for param in sig.parameters.values() if param.name not in ["task_manager"]],
            )
            cast("Any", partial_func).__signature__ = sig

            router_path(partial_func)

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
        if self._runner is not None:
            logger.warning("TaskManager is already running.")
            return
        logger.info("Starting TaskManager...")
        self._runner = Runner(
            redis_client=Redis(
                host=self._config.redis_host,
                port=self._config.redis_port,
                password=self._config.redis_password,
                db=self._config.redis_db,
            ),
            concurrent_tasks=self._config.concurrent_tasks,
            task_manager=self,
        )
        await self._runner.start()
        logger.info("Started TaskManager.")

    async def stop(self) -> None:
        if self._runner is None:
            logger.warning("TaskManager is not running.")
            return
        logger.info("Stopping TaskManager...")
        await self._runner.stop()
        self._runner = None
        logger.info("Stopped TaskManager.")

    def add_task_group(
        self,
        task_group: TaskGroup,
    ):
        for tg in self._task_groups:
            if tg.name == task_group.name:
                msg = f"Task group {task_group.name} already exists."
                raise RuntimeError(msg)
        self._task_groups.append(task_group)
