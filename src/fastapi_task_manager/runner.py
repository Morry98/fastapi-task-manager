import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from redis.asyncio import Redis

from fastapi_task_manager.coordinator import Coordinator
from fastapi_task_manager.leader_election import LeaderElector
from fastapi_task_manager.reconciler import Reconciler
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.worker_identity import WorkerIdentity
from fastapi_task_manager.statistics import StatisticsStorage
from fastapi_task_manager.stream_consumer import StreamConsumer

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager

logger = logging.getLogger("fastapi.task-manager.runner")


class Runner:
    """Task runner using Redis Streams with leader election.

    The Runner is responsible for executing scheduled tasks. It uses Redis Streams
    with leader election for task scheduling and consumer groups for execution.
    """

    def __init__(
        self,
        redis_client: Redis,
        concurrent_tasks: int,
        task_manager: "TaskManager",
    ):
        # Use WorkerIdentity for traceable worker identification
        self._worker = WorkerIdentity(task_manager.config.worker_service_name)
        self._uuid = self._worker.redis_safe_id
        # Initialize the key builder for centralized key construction
        self._key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)
        self._redis_client = redis_client
        self._semaphore = asyncio.Semaphore(concurrent_tasks)
        self._task_manager = task_manager
        # Initialize statistics storage with Redis Lists for atomic operations
        self._statistics = StatisticsStorage(
            redis_client=redis_client,
            max_entries=task_manager.config.statistics_history_runs,
            ttl_seconds=task_manager.config.statistics_redis_expiration,
        )

        # Stream mode components (initialized lazily in start())
        self._leader_elector: LeaderElector | None = None
        self._coordinator: Coordinator | None = None
        self._consumer: StreamConsumer | None = None
        self._reconciler: Reconciler | None = None
        self._coordinator_task: asyncio.Task | None = None
        self._consumer_task: asyncio.Task | None = None
        self._reconciler_task: asyncio.Task | None = None

    # ---------------------------------------------------------------------------
    # Properties exposed for the management API (health endpoint)
    # ---------------------------------------------------------------------------

    @property
    def worker_id(self) -> str:
        """Return the human-readable worker short ID."""
        return self._worker.short_id

    @property
    def worker_started_at(self) -> str:
        """Return the ISO timestamp when this worker was initialized."""
        return self._worker.started_at

    @property
    def is_leader(self) -> bool:
        """Return whether this worker currently holds leadership."""
        if self._leader_elector is None:
            return False
        return self._leader_elector.is_leader

    async def start(self) -> None:
        """Start the runner with Redis Streams."""
        # Check if already running
        if self._consumer_task:
            msg = "Runner is already running."
            logger.warning(msg)
            return

        # Verify Redis connection
        try:
            pong = await self._redis_client.ping()  # ty: ignore[invalid-await]
        except Exception as e:
            msg = f"Redis ping failed: {e!r}"
            raise ConnectionError(msg) from e
        if not pong:
            msg = "Redis ping returned falsy response"
            raise ConnectionError(msg)

        config = self._task_manager.config

        # Initialize leader elector
        self._leader_elector = LeaderElector(
            redis_client=self._redis_client,
            key_builder=self._key_builder,
            worker_identity=self._worker,
            lock_ttl=config.leader_lock_ttl,
            heartbeat_interval=config.leader_heartbeat_interval,
        )

        # Initialize stream consumer
        self._consumer = StreamConsumer(
            redis_client=self._redis_client,
            key_builder=self._key_builder,
            worker_identity=self._worker,
            task_manager=self._task_manager,
            semaphore=self._semaphore,
            statistics=self._statistics,
        )

        # Initialize coordinator
        self._coordinator = Coordinator(
            redis_client=self._redis_client,
            key_builder=self._key_builder,
            leader_elector=self._leader_elector,
            task_manager=self._task_manager,
        )

        # Initialize reconciler if enabled (leader only, but all workers start it;
        # the reconciler checks leadership internally before acting)
        if config.reconciliation_enabled:
            self._reconciler = Reconciler(
                redis_client=self._redis_client,
                key_builder=self._key_builder,
                leader_elector=self._leader_elector,
                task_manager=self._task_manager,
            )

        # Setup consumer groups for both high and low priority streams
        await self._consumer.setup_consumer_groups()

        # Start coordinator (handles leader election internally)
        self._coordinator_task = await self._coordinator.start()

        # Start consumer (runs on all workers, recovers pending messages on startup)
        self._consumer_task = await self._consumer.start()

        # Start reconciler if enabled
        if self._reconciler:
            self._reconciler_task = await self._reconciler.start()

        logger.info("Runner started. Worker: %s", self._worker)

    async def stop(self) -> None:
        """Stop the runner and all stream mode components gracefully."""
        if not self._consumer_task and not self._coordinator_task:
            msg = "Runner is not running."
            logger.warning(msg)
            return

        # Stop reconciler first (stop recovery actions)
        if self._reconciler:
            await self._reconciler.stop()
        if self._reconciler_task:
            self._reconciler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconciler_task
            self._reconciler_task = None

        # Stop coordinator (stop scheduling new tasks)
        if self._coordinator:
            await self._coordinator.stop()
        if self._coordinator_task:
            self._coordinator_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._coordinator_task
            self._coordinator_task = None

        # Stop consumer (stop processing tasks)
        if self._consumer:
            await self._consumer.stop()
        if self._consumer_task:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
            self._consumer_task = None

        # Release leadership if held
        if self._leader_elector:
            await self._leader_elector.release_leadership()

        # Clear references
        self._coordinator = None
        self._consumer = None
        self._reconciler = None
        self._leader_elector = None

        logger.info("Runner stopped.")
