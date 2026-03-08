"""Coordinator module - evaluates cron and publishes to stream (leader only).

This module provides the Coordinator class which is responsible for:
- Evaluating cron expressions for all registered tasks
- Publishing ready tasks to the Redis Stream
- Updating next_run timestamps for scheduled tasks

The Coordinator only performs its duties when the associated worker
is the leader. When not the leader, it periodically attempts to acquire
leadership via the LeaderElector.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from cronsim import CronSim
from redis.asyncio import Redis

from fastapi_task_manager.async_utils import interruptible_sleep
from fastapi_task_manager.leader_election import LeaderElector
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task
from fastapi_task_manager.task_group import TaskGroup

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager

logger = logging.getLogger("fastapi.task-manager.coordinator")


class Coordinator:
    """Evaluates cron expressions and publishes ready tasks to stream.

    The Coordinator is the "brain" of the task scheduling system in stream mode.
    It runs on all workers but only performs scheduling duties when the worker
    is the leader. This ensures that tasks are only scheduled once, avoiding
    duplicates.

    Responsibilities:
    - Check if tasks are due based on their cron expressions
    - Publish ready tasks to the Redis Stream
    - Update next_run timestamps after scheduling
    - Attempt to acquire leadership when not the leader

    The Coordinator does NOT execute tasks - that's handled by StreamConsumer.
    """

    def __init__(
        self,
        redis_client: Redis,
        key_builder: RedisKeyBuilder,
        leader_elector: LeaderElector,
        task_manager: "TaskManager",
    ) -> None:
        """Initialize the Coordinator.

        Args:
            redis_client: Async Redis client for stream operations.
            key_builder: RedisKeyBuilder instance for key construction.
            leader_elector: LeaderElector instance to check leadership status.
            task_manager: TaskManager instance containing registered task groups.
        """
        self._redis = redis_client
        self._keys = key_builder
        self._leader = leader_elector
        self._task_manager = task_manager
        self._running = False

    async def start(self) -> asyncio.Task:
        """Start the coordinator loop.

        Returns:
            The asyncio Task running the coordinator loop.
        """
        self._running = True
        return asyncio.create_task(self._run(), name="Coordinator")

    async def stop(self) -> None:
        """Stop the coordinator loop."""
        self._running = False

    async def _run(self) -> None:
        """Main coordinator loop.

        This loop continuously:
        1. Checks if this worker is the leader
        2. If not leader, attempts to acquire leadership
        3. If leader, evaluates all tasks and publishes ready ones

        The loop respects the configured poll_interval and leader_retry_interval.
        """
        config = self._task_manager.config

        while self._running:
            try:
                if not self._leader.is_leader:
                    # Not leader, try to acquire leadership
                    await self._leader.try_acquire_leadership()
                    if not self._leader.is_leader:
                        # Still not leader, wait and retry
                        await interruptible_sleep(config.leader_retry_interval, lambda: self._running)
                        continue

                # We are the leader - evaluate and publish tasks
                await self._evaluate_and_publish_all()
                await interruptible_sleep(config.poll_interval, lambda: self._running)

            except asyncio.CancelledError:
                logger.info("Coordinator loop cancelled")
                break
            except Exception:
                logger.exception("Error in coordinator loop")
                await interruptible_sleep(1, lambda: self._running)

    async def _evaluate_and_publish_all(self) -> None:
        """Check all tasks and publish ready ones to stream.

        Iterates through all task groups and their tasks, checking if each
        task is due for execution. Ready tasks are published to the appropriate
        Redis Stream (high or low priority) and their next_run timestamps are updated.
        """
        # Get both stream keys for high and low priority
        stream_key_high = self._keys.task_stream_high_key()
        stream_key_low = self._keys.task_stream_low_key()

        for task_group in self._task_manager.task_groups:
            for task in task_group.tasks:
                try:
                    if await self._is_task_due(task_group, task):
                        # Select stream based on task priority
                        stream_key = stream_key_high if task.high_priority else stream_key_low
                        await self._publish_task(stream_key, task_group, task)
                        await self._update_next_run(task_group, task)
                except Exception:
                    logger.exception(
                        "Error evaluating task %s/%s",
                        task_group.name,
                        task.name,
                    )

    async def _is_task_due(self, task_group: TaskGroup, task: Task) -> bool:
        """Check if a task is due for execution.

        A task is due if:
        1. It's not disabled
        2. Its next_run time is in the past (or not set)

        Args:
            task_group: The TaskGroup containing the task.
            task: The Task to check.

        Returns:
            True if the task should be executed, False otherwise.
        """
        keys = self._keys.get_task_keys(task_group.name, task.name)

        # Check if disabled
        disabled = await self._redis.get(keys.disabled)
        if disabled is not None:
            return False

        # Check if task is in backoff (retry_after timestamp in the future)
        retry_after_raw = await self._redis.get(keys.retry_after)
        if retry_after_raw is not None:
            if isinstance(retry_after_raw, bytes):
                retry_after_raw = retry_after_raw.decode("utf-8")
            if time.time() < float(retry_after_raw):
                logger.debug(
                    "Task %s/%s in backoff until %.0f, skipping",
                    task_group.name,
                    task.name,
                    float(retry_after_raw),
                )
                return False

        # Check next_run time
        next_run_b = await self._redis.get(keys.next_run)
        if next_run_b is None:
            # Never run before, due immediately
            return True

        # Decode the value if it's bytes
        if isinstance(next_run_b, bytes):
            next_run_b = next_run_b.decode("utf-8")

        next_run = datetime.fromtimestamp(float(next_run_b), tz=timezone.utc)
        return next_run <= datetime.now(timezone.utc)

    async def _publish_task(
        self,
        stream_key: str,
        task_group: TaskGroup,
        task: Task,
    ) -> str:
        """Publish a task to the Redis stream and track it in the scheduled set.

        Creates a message in the appropriate task stream (high or low priority)
        containing the task group name, task name, and scheduling timestamp.
        The stream is automatically trimmed to the configured max length.

        After publishing, the task identifier is added to the scheduled tracking
        SET so the Reconciler can detect lost tasks.

        Args:
            stream_key: The Redis key for the task stream (high or low).
            task_group: The TaskGroup containing the task.
            task: The Task to publish.

        Returns:
            The message ID assigned by Redis.
        """
        task_id = f"{task_group.name}:{task.name}"

        message_id = await self._redis.xadd(
            stream_key,
            {
                "group": task_group.name,
                "task": task.name,
                "scheduled_at": str(datetime.now(timezone.utc).timestamp()),
            },
            maxlen=self._task_manager.config.stream_max_len,
            approximate=True,  # Use ~ for efficiency
        )

        # Track the published task in the scheduled set for reconciliation
        await self._redis.sadd(self._keys.scheduled_set_key(), task_id)  # ty: ignore[invalid-await]

        # Decode message_id if bytes
        if isinstance(message_id, bytes):
            message_id = message_id.decode("utf-8")

        priority = "high" if task.high_priority else "low"
        logger.debug(
            "Published task %s/%s to %s priority stream (msg_id: %s)",
            task_group.name,
            task.name,
            priority,
            message_id,
        )
        return message_id

    async def _update_next_run(self, task_group: TaskGroup, task: Task) -> None:
        """Update the next_run timestamp for a task.

        Calculates the next execution time based on the task's cron expression
        and stores it in Redis with an appropriate TTL.

        Args:
            task_group: The TaskGroup containing the task.
            task: The Task to update.
        """
        keys = self._keys.get_task_keys(task_group.name, task.name)
        next_run = next(CronSim(task.expression, datetime.now(timezone.utc)))

        # Calculate TTL: at least initial_lock_ttl, or 2x the time until next run
        time_until_next = (next_run - datetime.now(timezone.utc)).total_seconds()
        ttl = max(
            int(time_until_next) * 2,
            self._task_manager.config.initial_lock_ttl,
        )
        await self._redis.set(keys.next_run, next_run.timestamp(), ex=ttl)

        logger.debug(
            "Updated next_run for %s/%s to %s",
            task_group.name,
            task.name,
            next_run.isoformat(),
        )
