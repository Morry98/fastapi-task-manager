"""Reconciliation module - detects and recovers lost tasks (leader only).

This module provides the Reconciler class which periodically verifies the
consistency between what should be running and what is actually running.

It handles three recovery scenarios:
1. **Overdue tasks**: Tasks whose next_run is in the past but are not in the
   stream and not currently executing. This happens when the leader crashes
   before publishing to the stream, or during a leader failover gap.
2. **Stale tracking entries**: Entries in the scheduled SET that no longer have
   a corresponding message in the stream or a running indicator. These are
   cleaned up to prevent the SET from growing indefinitely.
3. **Stuck pending messages**: Messages in the stream's Pending Entries List (PEL)
   that have been idle too long (consumer crashed before ACK). These are
   reclaimed via XAUTOCLAIM and reassigned to active consumers.

The Reconciler only runs on the leader worker to avoid duplicate recovery work.
"""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from fastapi_task_manager.async_utils import interruptible_sleep
from fastapi_task_manager.coordinator import STREAM_MAX_LEN
from fastapi_task_manager.leader_election import LeaderElector
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task
from fastapi_task_manager.task_group import TaskGroup

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager

logger = logging.getLogger("fastapi.task-manager.reconciler")


class Reconciler:
    """Periodic reconciliation loop that detects and recovers lost tasks.

    Runs on the leader only, at a configurable interval (default: 30s).
    Each cycle performs three checks:
    1. Find overdue tasks that are not scheduled or running, and republish them.
    2. Clean up stale entries in the scheduled tracking SET.
    3. Reclaim stuck pending messages from crashed consumers.
    """

    def __init__(
        self,
        redis_client: Redis,
        key_builder: RedisKeyBuilder,
        leader_elector: LeaderElector,
        task_manager: "TaskManager",
    ) -> None:
        """Initialize the Reconciler.

        Args:
            redis_client: Async Redis client for all Redis operations.
            key_builder: RedisKeyBuilder instance for key construction.
            leader_elector: LeaderElector to verify leadership before acting.
            task_manager: TaskManager containing registered task groups and config.
        """
        self._redis = redis_client
        self._keys = key_builder
        self._leader = leader_elector
        self._task_manager = task_manager
        self._running = False

    async def start(self) -> asyncio.Task:
        """Start the reconciliation loop.

        Returns:
            The asyncio Task running the reconciliation loop.
        """
        self._running = True
        return asyncio.create_task(self._run(), name="Reconciler")

    async def stop(self) -> None:
        """Stop the reconciliation loop."""
        self._running = False

    async def _run(self) -> None:
        """Main reconciliation loop.

        Sleeps for the configured interval between checks using short sleep
        increments so that stop() can interrupt promptly. Only performs
        reconciliation when this worker is the leader.
        """
        config = self._task_manager.config

        while self._running:
            try:
                # Sleep in short increments to allow prompt shutdown
                await interruptible_sleep(config.reconciliation_interval, lambda: self._running)
                if not self._running:
                    break

                if not self._leader.is_leader:
                    continue

                logger.debug("Reconciliation cycle starting")
                await self._check_overdue_tasks()
                await self._cleanup_stale_tracking()
                await self._reclaim_stuck_pending()
                logger.debug("Reconciliation cycle completed")

            except asyncio.CancelledError:
                logger.info("Reconciler loop cancelled")
                break
            except Exception:
                logger.exception("Error in reconciliation cycle")
                await interruptible_sleep(1, lambda: self._running)

    async def _check_overdue_tasks(self) -> None:
        """Find tasks that are overdue and not scheduled or running, then republish.

        A task is considered lost if:
        - It is not disabled
        - It is not in the scheduled tracking SET (not in the stream)
        - It does not have an active running key (not being executed)
        - Its next_run timestamp is in the past by more than the safety margin

        The safety margin (reconciliation_interval * 5) avoids race conditions
        with the Coordinator: it ensures the Coordinator has had plenty of
        scheduling cycles to publish the task before the Reconciler steps in.
        """
        config = self._task_manager.config
        # Safety margin to avoid double-publishing with the Coordinator
        overdue_margin = timedelta(seconds=config.reconciliation_interval * 5)
        scheduled_set_key = self._keys.scheduled_set_key()

        for task_group in self._task_manager.task_groups:
            for task in task_group.tasks:
                try:
                    await self._check_single_task(
                        task_group,
                        task,
                        scheduled_set_key,
                        overdue_margin,
                    )
                except Exception:
                    logger.exception(
                        "Error checking task %s/%s during reconciliation",
                        task_group.name,
                        task.name,
                    )

    async def _check_single_task(
        self,
        task_group: TaskGroup,
        task: Task,
        scheduled_set_key: str,
        overdue_margin: timedelta,
    ) -> None:
        """Check a single task for overdue status and republish if needed.

        Args:
            task_group: The TaskGroup containing the task.
            task: The Task to check.
            scheduled_set_key: Redis key for the scheduled tracking SET.
            overdue_margin: Safety margin past next_run before considering overdue.
        """
        task_id = f"{task_group.name}:{task.name}"
        keys = self._keys.get_task_keys(task_group.name, task.name)
        running_key = self._keys.running_task_key(task_group.name, task.name)

        # Skip disabled tasks
        disabled = await self._redis.get(keys.disabled)
        if disabled is not None:
            return

        # Skip if already scheduled (in stream) or currently running
        is_scheduled = await self._redis.sismember(scheduled_set_key, task_id)  # ty: ignore[invalid-await]
        if is_scheduled:
            return

        is_running = await self._redis.exists(running_key)
        if is_running:
            return

        # Check if the task is overdue
        next_run_b = await self._redis.get(keys.next_run)
        if next_run_b is None:
            # Never scheduled and not in stream -> publish it
            logger.warning(
                "Reconciliation: task %s/%s has no next_run and is not scheduled, republishing",
                task_group.name,
                task.name,
            )
            await self._republish_task(task_group, task)
            return

        # Decode the next_run value
        if isinstance(next_run_b, bytes):
            next_run_b = next_run_b.decode("utf-8")

        next_run = datetime.fromtimestamp(float(next_run_b), tz=timezone.utc)
        now = datetime.now(timezone.utc)

        if now > next_run + overdue_margin:
            logger.warning(
                "Reconciliation: task %s/%s is overdue by %s, republishing",
                task_group.name,
                task.name,
                now - next_run,
            )
            await self._republish_task(task_group, task)

    async def _republish_task(self, task_group: TaskGroup, task: Task) -> None:
        """Republish a lost task to the appropriate stream.

        Publishes the task to either the high or low priority stream based on
        the task's priority setting, and adds it to the scheduled tracking SET.

        Args:
            task_group: The TaskGroup containing the task.
            task: The Task to republish.
        """
        task_id = f"{task_group.name}:{task.name}"
        stream_key = self._keys.task_stream_high_key() if task.high_priority else self._keys.task_stream_low_key()

        message_id = await self._redis.xadd(
            stream_key,
            {
                "group": task_group.name,
                "task": task.name,
                "scheduled_at": str(datetime.now(timezone.utc).timestamp()),
                "reconciled": "1",
            },
            maxlen=STREAM_MAX_LEN,
            approximate=True,
        )

        # Track in the scheduled set
        await self._redis.sadd(self._keys.scheduled_set_key(), task_id)  # ty: ignore[invalid-await]

        # Decode message_id for logging
        if isinstance(message_id, bytes):
            message_id = message_id.decode("utf-8")

        priority = "high" if task.high_priority else "low"
        logger.info(
            "Reconciliation: republished task %s/%s to %s stream (msg_id: %s)",
            task_group.name,
            task.name,
            priority,
            message_id,
        )

    async def _cleanup_stale_tracking(self) -> None:
        """Remove stale entries from the scheduled tracking SET.

        An entry is stale if the task is neither running (no running key)
        nor pending in the stream. This can happen when a consumer finishes
        a task but fails to remove the tracking entry (e.g., partial failure
        during cleanup).
        """
        scheduled_set_key = self._keys.scheduled_set_key()
        members = await self._redis.smembers(scheduled_set_key)  # ty: ignore[invalid-await]

        for member in members:
            # Decode member if bytes
            task_id = member.decode("utf-8") if isinstance(member, bytes) else member

            # Parse "group:task" format
            if ":" not in task_id:
                # Malformed entry, remove it
                await self._redis.srem(scheduled_set_key, member)  # ty: ignore[invalid-await]
                continue

            group_name, task_name = task_id.split(":", 1)
            running_key = self._keys.running_task_key(group_name, task_name)

            # If the task is still running, the entry is valid
            is_running = await self._redis.exists(running_key)
            if is_running:
                continue

            # Check if the task still exists in registered task groups
            task = self._find_task(group_name, task_name)
            if task is None:
                # Task no longer registered, clean up the tracking entry
                logger.info(
                    "Reconciliation: removing stale tracking for unregistered task %s",
                    task_id,
                )
                await self._redis.srem(scheduled_set_key, member)  # ty: ignore[invalid-await]

    async def _reclaim_stuck_pending(self) -> None:
        """Reclaim messages stuck in the Pending Entries List (PEL).

        Finds messages that have been pending for longer than
        running_heartbeat_interval * 9 (in ms) (consumer crashed before ACK). For each
        stuck message, the Reconciler:
        1. ACKs the old pending message (removes it from the PEL)
        2. Re-publishes it as a new message via XADD

        This approach ensures the message goes back into the stream as a fresh
        entry, so the consumer group distributes it evenly across all active
        workers - rather than forcing it onto a single consumer via XCLAIM.
        """
        config = self._task_manager.config
        stream_keys = self._keys.get_stream_keys()
        # Derived from running_heartbeat_interval: TTL is interval * 3,
        # and we wait 3x the TTL to be sure the heartbeat has expired
        min_idle = math.ceil(config.running_heartbeat_interval * 9) * 1000

        for stream_key, label in [
            (stream_keys.task_stream_high, "high"),
            (stream_keys.task_stream_low, "low"),
        ]:
            try:
                # Find messages that have been pending too long
                pending_info = await self._redis.xpending_range(
                    stream_key,
                    stream_keys.consumer_group,
                    min="-",
                    max="+",
                    count=100,
                )

                if not pending_info:
                    continue

                for entry in pending_info:
                    idle_time = entry.get("time_since_delivered", 0)
                    if idle_time <= min_idle:
                        continue

                    message_id = entry.get("message_id")
                    if message_id is None:
                        continue

                    # Decode message_id if bytes
                    if isinstance(message_id, bytes):
                        message_id = message_id.decode("utf-8")

                    await self._requeue_pending_message(
                        stream_key,
                        stream_keys.consumer_group,
                        message_id,
                        label,
                    )

            except ResponseError as e:
                if "unknown command" in str(e).lower():
                    logger.debug("XPENDING not available, skipping pending check for %s stream", label)
                else:
                    logger.exception("Error checking pending messages in %s stream", label)
            except Exception:
                logger.exception("Error checking pending messages in %s stream", label)

    async def _requeue_pending_message(
        self,
        stream_key: str,
        group_name: str,
        message_id: str,
        priority_label: str,
    ) -> None:
        """ACK a stuck pending message and re-publish it as a new stream entry.

        This makes the message available to all consumers via normal consumer
        group distribution, instead of forcing it onto a specific consumer.

        Args:
            stream_key: The Redis stream key (high or low priority).
            group_name: The consumer group name.
            message_id: The stuck message ID to requeue.
            priority_label: "high" or "low" for logging.
        """
        # Read the original message data before ACK'ing
        messages = await self._redis.xrange(stream_key, min=message_id, max=message_id, count=1)

        if not messages:
            # Message was already trimmed from the stream, just ACK to clean PEL
            await self._redis.xack(stream_key, group_name, message_id)
            logger.debug(
                "Reconciliation: ACK'd orphan pending message %s (already trimmed from %s stream)",
                message_id,
                priority_label,
            )
            return

        # Extract the original message data
        _msg_id, data = messages[0]

        # ACK the old message to remove it from the PEL and delete it from the stream
        await self._redis.xack(stream_key, group_name, message_id)
        await self._redis.xdel(stream_key, message_id)

        # Re-publish as a new message so all consumers can compete for it
        new_message_id = await self._redis.xadd(
            stream_key,
            {
                **{
                    (k.decode("utf-8") if isinstance(k, bytes) else k): (
                        v.decode("utf-8") if isinstance(v, bytes) else v
                    )
                    for k, v in data.items()
                },
                "requeued_from": message_id,
            },
            maxlen=STREAM_MAX_LEN,
            approximate=True,
        )

        # Decode new_message_id for logging
        if isinstance(new_message_id, bytes):
            new_message_id = new_message_id.decode("utf-8")

        logger.warning(
            "Reconciliation: requeued stuck %s priority message %s -> %s",
            priority_label,
            message_id,
            new_message_id,
        )

    def _find_task(self, group_name: str, task_name: str) -> Task | None:
        """Find a task by group and task name in registered task groups.

        Args:
            group_name: The task group name.
            task_name: The task name.

        Returns:
            The Task if found, None otherwise.
        """
        for task_group in self._task_manager.task_groups:
            if task_group.name == group_name:
                for task in task_group.tasks:
                    if task.name == task_name:
                        return task
        return None
