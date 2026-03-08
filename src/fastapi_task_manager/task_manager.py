import functools
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, FastAPI
from redis.asyncio import Redis

from fastapi_task_manager.config import Config
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.runner import Runner
from fastapi_task_manager.schema.health import ConfigResponse, HealthResponse
from fastapi_task_manager.schema.task import (
    DynamicTaskResponse,
    RegisteredFunctionsResponse,
    TaskActionResponse,
    TaskDetailed,
)
from fastapi_task_manager.schema.task_group import TaskGroup as TaskGroupSchema
from fastapi_task_manager.task_group import TaskGroup
from fastapi_task_manager.task_router_services import (
    clear_statistics,
    create_dynamic_task,
    delete_dynamic_task,
    disable_tasks,
    enable_tasks,
    get_config,
    get_health,
    get_registered_functions,
    get_task_groups,
    get_tasks,
    reset_retry,
    trigger_tasks,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("fastapi.task-manager")


class TaskManager:
    def __init__(
        self,
        app: FastAPI,
        config: Config,
    ):
        self._config = config
        self._app = app
        self._runner: Runner | None = None
        self._redis_client: Redis | None = None
        self._task_groups: list[TaskGroup] = []

        logger.setLevel(logging.NOTSET)

        self.append_to_app_lifecycle(app)

    # ---------------------------------------------------------------------------
    # Properties
    # ---------------------------------------------------------------------------

    @property
    def task_groups(self) -> list[TaskGroup]:
        return self._task_groups.copy()

    @property
    def config(self) -> Config:
        return self._config

    @property
    def redis_client(self) -> Redis:
        """Return the shared async Redis client.

        Raises RuntimeError if the TaskManager has not been started yet.
        """
        if self._redis_client is None:
            msg = "TaskManager has not been started. Redis client is not available."
            raise RuntimeError(msg)
        return self._redis_client

    @property
    def runner(self) -> Runner | None:
        """Return the current Runner instance, or None if not started."""
        return self._runner

    # ---------------------------------------------------------------------------
    # Health check API (for programmatic use)
    # ---------------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Synchronous check: True if the runner has been started.

        This is a cheap, non-blocking check that can be used in sync code.
        It does NOT verify Redis connectivity. For a full check use
        ``is_healthy()`` or ``health_check()``.

        Example::

            @app.get("/health")
            async def health():
                return {"task_manager_running": task_manager.is_running}
        """
        return self._runner is not None

    async def is_healthy(self) -> bool:
        """Async check: True if the runner is alive AND Redis is reachable.

        Convenience method that returns a single boolean suitable for
        inclusion in an application health endpoint.

        Example::

            @app.get("/health")
            async def health():
                return {
                    "task_manager": await task_manager.is_healthy(),
                    "other_service": ...,
                }
        """
        if self._runner is None or self._redis_client is None:
            return False
        try:
            return bool(await self._redis_client.ping())  # ty: ignore[invalid-await]
        except Exception:
            return False

    async def health_check(self) -> HealthResponse:
        """Async check: returns the full ``HealthResponse`` model.

        Same data returned by the ``GET /health`` router endpoint, but
        callable directly from application code without HTTP.

        Example::

            @app.get("/health")
            async def health():
                tm_health = await task_manager.health_check()
                return {
                    "task_manager": tm_health.model_dump(),
                    "other_service": ...,
                }
        """
        return await get_health(self)

    # ---------------------------------------------------------------------------
    # Router
    # ---------------------------------------------------------------------------

    def get_manager_router(
        self,
    ) -> APIRouter:
        router = APIRouter()
        func: Callable

        # Define all route registrations: (service_function, route_decorator)
        for func, router_path in {
            # --- GET endpoints ---
            (
                cast("Callable[..., Any]", get_task_groups),
                router.get(
                    "/task-groups",
                    response_model_by_alias=True,
                    response_model=list[TaskGroupSchema],
                    description="Get task groups with optional filtering",
                    name="Get task groups",
                ),
            ),
            (
                cast("Callable[..., Any]", get_tasks),
                router.get(
                    "/tasks",
                    response_model_by_alias=True,
                    response_model=list[TaskDetailed],
                    description="Get tasks with execution statistics and running state",
                    name="Get tasks",
                ),
            ),
            (
                cast("Callable[..., Any]", get_health),
                router.get(
                    "/health",
                    response_model_by_alias=True,
                    response_model=HealthResponse,
                    description="Health check: runner status, Redis connectivity, worker info",
                    name="Health check",
                ),
            ),
            (
                cast("Callable[..., Any]", get_config),
                router.get(
                    "/config",
                    response_model_by_alias=True,
                    response_model=ConfigResponse,
                    description="Current operational configuration (no secrets)",
                    name="Get config",
                ),
            ),
            # --- POST action endpoints ---
            (
                cast("Callable[..., Any]", disable_tasks),
                router.post(
                    "/tasks/disable",
                    response_model_by_alias=True,
                    response_model=TaskActionResponse,
                    description="Disable matching tasks (bulk)",
                    name="Disable tasks",
                ),
            ),
            (
                cast("Callable[..., Any]", enable_tasks),
                router.post(
                    "/tasks/enable",
                    response_model_by_alias=True,
                    response_model=TaskActionResponse,
                    description="Enable matching tasks (bulk)",
                    name="Enable tasks",
                ),
            ),
            (
                cast("Callable[..., Any]", reset_retry),
                router.post(
                    "/tasks/reset-retry",
                    response_model_by_alias=True,
                    response_model=TaskActionResponse,
                    description="Reset retry backoff for matching tasks (bulk)",
                    name="Reset retry",
                ),
            ),
            (
                cast("Callable[..., Any]", trigger_tasks),
                router.post(
                    "/tasks/trigger",
                    response_model_by_alias=True,
                    response_model=TaskActionResponse,
                    description="Trigger immediate execution of matching tasks (bulk)",
                    name="Trigger tasks",
                ),
            ),
            # --- Dynamic task endpoints ---
            (
                cast("Callable[..., Any]", create_dynamic_task),
                router.post(
                    "/tasks",
                    response_model_by_alias=True,
                    response_model=DynamicTaskResponse,
                    description="Create a dynamic task from a registered function",
                    name="Create dynamic task",
                ),
            ),
            (
                cast("Callable[..., Any]", delete_dynamic_task),
                router.delete(
                    "/tasks",
                    response_model_by_alias=True,
                    response_model=DynamicTaskResponse,
                    description="Delete a dynamic task and clean up its Redis keys",
                    name="Delete dynamic task",
                ),
            ),
            (
                cast("Callable[..., Any]", get_registered_functions),
                router.get(
                    "/functions",
                    response_model_by_alias=True,
                    response_model=RegisteredFunctionsResponse,
                    description="List registered functions available for dynamic task creation",
                    name="Get registered functions",
                ),
            ),
            # --- DELETE endpoints ---
            (
                cast("Callable[..., Any]", clear_statistics),
                router.delete(
                    "/tasks/statistics",
                    response_model_by_alias=True,
                    response_model=TaskActionResponse,
                    description="Clear execution history for matching tasks (bulk)",
                    name="Clear statistics",
                ),
            ),
        }:
            partial_func = functools.partial(
                func,
                self,
            )
            router_path(partial_func)
        return router

    # ---------------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------------

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

        # Create and store the shared async Redis client
        self._redis_client = Redis(
            host=self._config.redis_host,
            port=self._config.redis_port,
            password=self._config.redis_password,
            db=self._config.redis_db,
        )

        # Load persisted dynamic tasks from Redis before starting the Runner
        await self._load_dynamic_tasks()

        self._runner = Runner(
            redis_client=self._redis_client,
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

        # Close the shared Redis connection
        if self._redis_client is not None:
            await self._redis_client.aclose()
            self._redis_client = None

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

    async def _load_dynamic_tasks(self) -> None:
        """Load persisted dynamic task definitions from Redis on startup.

        Reads all entries from the dynamic_tasks Redis Hash and adds them
        to the corresponding in-memory TaskGroups via add_dynamic_task().
        Silently skips tasks whose function is not registered (e.g., after
        a code change that removed the function).
        """
        if self._redis_client is None:
            return

        key_builder = RedisKeyBuilder(self._config.redis_key_prefix)
        hash_key = key_builder.dynamic_tasks_key()

        # Read all persisted dynamic task definitions
        raw_definitions = await self._redis_client.hgetall(hash_key)  # ty: ignore[invalid-await]
        if not raw_definitions:
            return

        loaded_count = 0
        for _field, raw_value in raw_definitions.items():
            try:
                # Decode bytes if needed
                value = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else raw_value
                definition = json.loads(value)

                # Find the target TaskGroup
                target_group: TaskGroup | None = None
                for tg in self._task_groups:
                    if tg.name == definition["task_group_name"]:
                        target_group = tg
                        break

                if target_group is None:
                    logger.warning(
                        "Skipping dynamic task '%s': task group '%s' not found",
                        definition.get("name", "unknown"),
                        definition["task_group_name"],
                    )
                    continue

                # Check if the function is still registered
                if definition["function_name"] not in target_group.function_registry:
                    logger.warning(
                        "Skipping dynamic task '%s': function '%s' not registered in group '%s'",
                        definition.get("name", "unknown"),
                        definition["function_name"],
                        definition["task_group_name"],
                    )
                    continue

                target_group.add_dynamic_task(
                    function_name=definition["function_name"],
                    cron_expression=definition["cron_expression"],
                    kwargs=definition.get("kwargs"),
                    name=definition.get("name"),
                    description=definition.get("description"),
                    high_priority=definition.get("high_priority", False),
                    tags=definition.get("tags"),
                    retry_backoff=definition.get("retry_backoff"),
                    retry_backoff_max=definition.get("retry_backoff_max"),
                )
                loaded_count += 1

            except Exception:
                logger.exception("Failed to load dynamic task definition")

        if loaded_count:
            logger.info("Loaded %d dynamic task(s) from Redis", loaded_count)
