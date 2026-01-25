"""Stream consumer module - consumes and executes tasks from Redis Streams.

This module provides the StreamConsumer class which is responsible for:
- Setting up the Redis consumer groups for dual-queue (high/low priority)
- Consuming tasks from the appropriate stream based on priority and capacity
- Executing task functions with proper concurrency control
- Acknowledging completed tasks with XACK
- Recording execution statistics

The dual-queue design ensures:
- High priority tasks are always attempted first
- Low priority tasks are only read when the worker has available capacity
- Workers without capacity don't consume low priority messages, leaving them
  for other workers with available slots

The StreamConsumer runs on ALL workers (both leader and followers),
enabling horizontal scaling of task execution.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task
from fastapi_task_manager.schema.worker_identity import WorkerIdentity
from fastapi_task_manager.statistics import StatisticsStorage

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager

logger = logging.getLogger("fastapi.task-manager")

# Short sleep duration when no messages or no capacity (50ms)
NO_WORK_SLEEP_SECONDS = 0.05


class StreamConsumer:
    """Consumes tasks from dual Redis Streams (high/low priority) and executes them.

    Uses a dual-queue design where:
    - High priority stream is always checked first
    - Low priority stream is only read when semaphore has available slots
    - If no capacity, messages are left in the stream for other workers

    The consumer uses non-blocking reads for high priority and short-blocking
    reads for low priority to balance responsiveness with efficiency.

    Responsibilities:
    - Setup consumer groups for both streams
    - Check semaphore capacity before reading low priority
    - Consume messages using XREADGROUP
    - Execute task functions (sync or async) in parallel
    - Acknowledge successful executions with XACK
    - Record execution statistics
    - Respect concurrency limits via semaphore
    """

    def __init__(
        self,
        redis_client: Redis,
        key_builder: RedisKeyBuilder,
        worker_identity: WorkerIdentity,
        task_manager: "TaskManager",
        semaphore: asyncio.Semaphore,
        statistics: StatisticsStorage,
    ) -> None:
        """Initialize the StreamConsumer.

        Args:
            redis_client: Async Redis client for stream operations.
            key_builder: RedisKeyBuilder instance for key construction.
            worker_identity: WorkerIdentity instance for this worker.
            task_manager: TaskManager instance containing registered task groups.
            semaphore: asyncio.Semaphore for concurrency control.
            statistics: StatisticsStorage for recording execution stats.
        """
        self._redis = redis_client
        self._keys = key_builder
        self._worker = worker_identity
        self._task_manager = task_manager
        self._semaphore = semaphore
        self._statistics = statistics
        self._running = False
        # Track running tasks for graceful shutdown
        self._running_tasks: set[asyncio.Task] = set()

    async def setup_consumer_groups(self) -> None:
        """Create consumer groups for both streams if they don't exist.

        Uses XGROUP CREATE with MKSTREAM to create both the stream and
        consumer group atomically. If the group already exists, the
        BUSYGROUP error is caught and ignored.

        The consumer groups are created with ID "$" which means consumers
        will only receive new messages (not historical ones).
        """
        stream_keys = self._keys.get_stream_keys()
        group_name = stream_keys.consumer_group

        # Setup consumer group for high priority stream
        await self._create_consumer_group(
            stream_keys.task_stream_high,
            group_name,
            "high priority",
        )

        # Setup consumer group for low priority stream
        await self._create_consumer_group(
            stream_keys.task_stream_low,
            group_name,
            "low priority",
        )

    async def _create_consumer_group(
        self,
        stream_key: str,
        group_name: str,
        stream_label: str,
    ) -> None:
        """Create a consumer group for a specific stream.

        Args:
            stream_key: The Redis stream key.
            group_name: The consumer group name.
            stream_label: Human-readable label for logging.
        """
        try:
            await self._redis.xgroup_create(
                stream_key,
                group_name,
                id="$",  # Only new messages
                mkstream=True,  # Create stream if not exists
            )
            logger.info(
                "Created consumer group '%s' for %s stream '%s'",
                group_name,
                stream_label,
                stream_key,
            )
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(
                    "Consumer group '%s' already exists for %s stream",
                    group_name,
                    stream_label,
                )
            else:
                raise

    async def start(self) -> asyncio.Task:
        """Start the consumer loop.

        Returns:
            The asyncio Task running the consumer loop.
        """
        self._running = True
        return asyncio.create_task(self._consume_loop(), name="StreamConsumer")

    async def stop(self) -> None:
        """Stop the consumer loop and wait for running tasks to complete."""
        self._running = False

        # Wait for all running tasks to complete
        if self._running_tasks:
            logger.info("Waiting for %d running tasks to complete...", len(self._running_tasks))
            await asyncio.gather(*self._running_tasks, return_exceptions=True)

    async def _consume_loop(self) -> None:
        """Main consumer loop with dual-queue priority logic.

        The loop follows this priority:
        1. If semaphore has capacity, try to read from high priority stream
        2. If no high priority message, try low priority stream
        3. If no capacity or no messages, sleep briefly and retry

        This ensures high priority tasks are always processed first, and
        low priority tasks don't block the queue when workers are at capacity.
        """
        stream_keys = self._keys.get_stream_keys()
        config = self._task_manager.config

        while self._running:
            try:
                # Check if we have available capacity (semaphore not fully locked)
                if not self._semaphore.locked():
                    # Try high priority stream first (non-blocking)
                    result = await self._try_read_stream(
                        stream_keys.task_stream_high,
                        stream_keys.consumer_group,
                        block_ms=0,  # Non-blocking for high priority
                    )

                    if result:
                        message_id, data = result
                        self._spawn_task(message_id, data, is_high_priority=True)
                        continue

                    # No high priority, try low priority (short blocking)
                    result = await self._try_read_stream(
                        stream_keys.task_stream_low,
                        stream_keys.consumer_group,
                        block_ms=config.stream_block_ms,
                    )

                    if result:
                        message_id, data = result
                        self._spawn_task(message_id, data, is_high_priority=False)
                        continue

                # No capacity or no messages - short sleep to avoid busy loop
                await asyncio.sleep(NO_WORK_SLEEP_SECONDS)

            except asyncio.CancelledError:
                logger.info("Consumer loop cancelled")
                break
            except Exception:
                logger.exception("Error in consumer loop")
                await asyncio.sleep(1)

    async def _try_read_stream(
        self,
        stream_key: str,
        group_name: str,
        block_ms: int,
    ) -> tuple[str, dict] | None:
        """Try to read a single message from a stream.

        Args:
            stream_key: The Redis stream key to read from.
            group_name: The consumer group name.
            block_ms: How long to block waiting for a message (0 = non-blocking).

        Returns:
            Tuple of (message_id, data) if a message was read, None otherwise.
        """
        messages = await self._redis.xreadgroup(
            groupname=group_name,
            consumername=self._worker.redis_safe_id,
            streams={stream_key: ">"},
            count=1,  # Read one message at a time
            block=block_ms,
        )

        if not messages:
            return None

        # Extract the first message from the response
        # Response format: [(stream_name, [(message_id, data), ...])]
        for _stream_name, stream_messages in messages:
            for msg_id, data in stream_messages:
                # Decode message_id if bytes
                decoded_id = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id
                return decoded_id, data

        return None

    def _spawn_task(
        self,
        message_id: str,
        data: dict,
        is_high_priority: bool,
    ) -> None:
        """Spawn an async task to process the message.

        The spawned task will acquire the semaphore, execute the task,
        record statistics, and acknowledge the message.

        Args:
            message_id: The Redis message ID.
            data: The message data containing task information.
            is_high_priority: Whether this is from the high priority stream.
        """
        task = asyncio.create_task(
            self._process_message(message_id, data, is_high_priority),
            name=f"Task-{message_id}",
        )
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

    async def _process_message(
        self,
        message_id: str,
        data: dict,
        is_high_priority: bool,
    ) -> None:
        """Process a single message from the stream.

        Acquires the semaphore, extracts task information, finds the
        corresponding task definition, and executes it.

        Args:
            message_id: The Redis message ID.
            data: The message data containing task information.
            is_high_priority: Whether this is from the high priority stream.
        """

        # Execute with semaphore to respect concurrency limits
        async with self._semaphore:
            # Extract and decode message fields
            group_name = self._decode_field(data.get("group", ""))
            task_name = self._decode_field(data.get("task", ""))

            priority_label = "high" if is_high_priority else "low"
            logger.debug(
                "Processing message %s: %s/%s (priority: %s)",
                message_id,
                group_name,
                task_name,
                priority_label,
            )

            # Find the task definition
            task = self._find_task(group_name, task_name)
            if task is None:
                logger.warning(
                    "Task not found: %s/%s, acknowledging to prevent reprocessing",
                    group_name,
                    task_name,
                )
                await self._ack_message(message_id, is_high_priority)
                return

            await self._execute_and_ack(message_id, group_name, task, is_high_priority)

    def _decode_field(self, value: str | bytes) -> str:
        """Decode a field value from bytes to string if necessary.

        Args:
            value: The field value, potentially as bytes.

        Returns:
            The decoded string value.
        """
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    async def _execute_and_ack(
        self,
        message_id: str,
        group_name: str,
        task: Task,
        is_high_priority: bool,
    ) -> None:
        """Execute task and acknowledge on completion.

        Executes the task function (handling both sync and async functions),
        records execution statistics, and acknowledges the message on success.

        Args:
            message_id: The Redis message ID to acknowledge.
            group_name: The task group name for statistics recording.
            task: The Task to execute.
            is_high_priority: Whether this is from the high priority stream.
        """
        keys = self._keys.get_task_keys(group_name, task.name)
        start = time.monotonic_ns()

        try:
            # Execute the task function
            if asyncio.iscoroutinefunction(task.function):
                await task.function(**(task.kwargs or {}))
            else:
                # Run sync functions in a thread to avoid blocking
                await asyncio.to_thread(task.function, **(task.kwargs or {}))

            end = time.monotonic_ns()

            # Record execution statistics
            await self._statistics.record_execution(
                runs_key=keys.runs,
                durations_key=keys.durations_second,
                timestamp=datetime.now(timezone.utc).timestamp(),
                duration_seconds=(end - start) / 1e9,
            )

            # Acknowledge successful execution
            await self._ack_message(message_id, is_high_priority)

            logger.debug(
                "Task %s/%s completed successfully (%.3fs)",
                group_name,
                task.name,
                (end - start) / 1e9,
            )

        except Exception:
            logger.exception("Task %s/%s failed", group_name, task.name)
            # TODO: Implement retry logic and DLQ (Dead Letter Queue)
            # For now, don't ACK - message remains pending for potential retry
            # Future implementation should:
            # - Track retry count
            # - Move to DLQ after max retries
            # - Support configurable retry policies

    async def _ack_message(self, message_id: str, is_high_priority: bool) -> None:
        """Acknowledge a message as successfully processed.

        Removes the message from the pending entries list for this consumer.
        Once acknowledged, the message won't be redelivered.

        Args:
            message_id: The Redis message ID to acknowledge.
            is_high_priority: Whether this is from the high priority stream.
        """
        stream_keys = self._keys.get_stream_keys()
        stream_key = stream_keys.task_stream_high if is_high_priority else stream_keys.task_stream_low

        await self._redis.xack(
            stream_key,
            stream_keys.consumer_group,
            message_id,
        )

    def _find_task(self, group_name: str, task_name: str) -> Task | None:
        """Find a task by group and task name.

        Searches through all registered task groups to find the matching task.

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
