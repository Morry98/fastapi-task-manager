"""Leader election module using Redis distributed lock.

This module provides the LeaderElector class which manages leader election
among multiple worker instances using a Redis-based distributed lock with
heartbeat mechanism.

The leader is responsible for evaluating cron expressions and publishing
ready tasks to the Redis Stream. All workers (including the leader) consume
and execute tasks from the stream.

Leader election uses SET NX (set if not exists) with TTL for the lock,
and periodic heartbeat renewal to maintain leadership.
"""

import asyncio
import contextlib
import logging

from redis.asyncio import Redis

from fastapi_task_manager.async_utils import interruptible_sleep
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.worker_identity import WorkerIdentity

logger = logging.getLogger("fastapi.task-manager.leader")


class LeaderElector:
    """Manages leader election using Redis distributed lock with heartbeat.

    This class handles the acquisition, maintenance, and release of leadership
    among multiple worker instances. Leadership is acquired using SET NX
    (atomic set-if-not-exists) and maintained through periodic heartbeat
    renewals.

    The leader is responsible for:
    - Evaluating cron expressions for all tasks
    - Publishing ready tasks to the Redis Stream
    - Maintaining the leadership lock via heartbeat

    Attributes:
        is_leader: Property indicating if this worker is currently the leader.
    """

    def __init__(
        self,
        redis_client: Redis,
        key_builder: RedisKeyBuilder,
        worker_identity: WorkerIdentity,
        lock_ttl: int = 10,
        heartbeat_interval: float = 3.0,
    ) -> None:
        """Initialize the LeaderElector.

        Args:
            redis_client: Async Redis client for lock operations.
            key_builder: RedisKeyBuilder instance for key construction.
            worker_identity: WorkerIdentity instance for this worker.
            lock_ttl: Time-to-live for the leader lock in seconds.
                Should be greater than heartbeat_interval * 3 to allow
                for network latency and temporary failures.
            heartbeat_interval: Interval between lock renewals in seconds.
                Should be significantly less than lock_ttl to ensure
                the lock doesn't expire during normal operation.
        """
        self._redis = redis_client
        self._keys = key_builder
        self._worker = worker_identity
        self._lock_ttl = lock_ttl
        self._heartbeat_interval = heartbeat_interval
        self._is_leader = False
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def is_leader(self) -> bool:
        """Check if this worker is currently the leader.

        Returns:
            True if this worker holds the leadership lock, False otherwise.
        """
        return self._is_leader

    async def try_acquire_leadership(self) -> bool:
        """Attempt to become the leader using SET NX.

        Tries to acquire the leadership lock atomically. If successful,
        starts the heartbeat task to maintain leadership.

        Returns:
            True if leadership was acquired, False if another worker
            already holds the lock.
        """
        acquired = await self._redis.set(
            self._keys.leader_lock_key(),
            self._worker.redis_safe_id,
            nx=True,
            ex=self._lock_ttl,
        )
        if acquired:
            self._is_leader = True
            self._start_heartbeat()
            logger.info("Worker %s became LEADER", self._worker.short_id)
        return bool(acquired)

    def _start_heartbeat(self) -> None:
        """Start the heartbeat task to maintain leadership.

        Creates an async task that periodically renews the leadership lock.
        If the task is already running, this method does nothing.
        """
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(),
                name="LeaderHeartbeat",
            )

    async def _heartbeat_loop(self) -> None:
        """Periodically renew leadership lock.

        This loop runs while the worker is leader, renewing the lock
        at regular intervals. If renewal fails (lock expired or stolen),
        the worker loses leadership and the loop exits.
        """
        while self._is_leader:
            await interruptible_sleep(self._heartbeat_interval, lambda: self._is_leader)
            try:
                # Renew only if we still own the lock (XX = only if exists)
                # We also verify ownership by checking if the value matches
                current_value = await self._redis.get(self._keys.leader_lock_key())
                if current_value is None:
                    logger.warning(
                        "Worker %s lost leadership - lock expired",
                        self._worker.short_id,
                    )
                    self._is_leader = False
                    break

                # Decode the value if it's bytes
                if isinstance(current_value, bytes):
                    current_value = current_value.decode("utf-8")

                if current_value != self._worker.redis_safe_id:
                    logger.warning(
                        "Worker %s lost leadership - lock stolen by another worker",
                        self._worker.short_id,
                    )
                    self._is_leader = False
                    break

                # Renew the lock
                renewed = await self._redis.set(
                    self._keys.leader_lock_key(),
                    self._worker.redis_safe_id,
                    xx=True,  # Only if exists
                    ex=self._lock_ttl,
                )
                if not renewed:
                    logger.warning(
                        "Worker %s lost leadership - renewal failed",
                        self._worker.short_id,
                    )
                    self._is_leader = False
                    break

                logger.debug(
                    "Worker %s renewed leadership lock",
                    self._worker.short_id,
                )

            except asyncio.CancelledError:
                # Task was cancelled, exit gracefully
                logger.debug("Heartbeat loop cancelled")
                break
            except Exception:
                logger.exception("Error renewing leader lock")
                self._is_leader = False
                break

    async def release_leadership(self) -> None:
        """Gracefully release leadership on shutdown.

        Stops the heartbeat task and releases the leadership lock if
        this worker currently holds it. Uses a Lua script to ensure
        atomic check-and-delete (only deletes if we own the lock).
        """
        # Stop heartbeat task
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

        if self._is_leader:
            # Only delete if we own the lock (using Lua for atomicity)
            # This prevents accidentally deleting a lock that was acquired
            # by another worker after our lock expired
            lua_script = """
            if redis.call("GET", KEYS[1]) == ARGV[1] then
                return redis.call("DEL", KEYS[1])
            else
                return 0
            end
            """
            try:
                result = await self._redis.eval(  # ty: ignore[invalid-await]
                    lua_script,
                    1,
                    self._keys.leader_lock_key(),
                    self._worker.redis_safe_id,
                )
                if result:
                    logger.info("Worker %s released leadership", self._worker.short_id)
                else:
                    logger.debug(
                        "Worker %s lock already released or owned by another",
                        self._worker.short_id,
                    )
            except Exception:
                logger.exception("Error releasing leader lock")

            self._is_leader = False
