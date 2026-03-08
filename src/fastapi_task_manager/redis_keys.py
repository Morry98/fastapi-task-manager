"""Redis key builder module for centralized key construction.

This module provides a centralized way to build Redis keys used throughout
the FastAPI Task Manager. All keys follow a consistent pattern to ensure
proper namespacing and avoid key collisions across different task groups
and tasks.

Key Pattern: {prefix}_{group}_{task}_{suffix}

Where:
    - prefix: Application-wide namespace (from Config.redis_key_prefix)
    - group: Task group name (from TaskGroup)
    - task: Individual task name (function name)
    - suffix: Key type identifier (next_run, disabled, etc.)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StreamKeys:
    """Container for Redis Stream related keys.

    This immutable dataclass holds all the Redis keys needed for Redis Streams
    operation, including the dual task streams (high/low priority), consumer group,
    leader election, and reconciliation tracking.

    Attributes:
        task_stream_high: Key for the high priority Redis Stream.
        task_stream_low: Key for the low priority Redis Stream.
        consumer_group: Name of the consumer group for task workers.
        leader_lock: Key used for leader election distributed lock.
        scheduled_set: Key for the SET tracking tasks currently in the stream.
    """

    task_stream_high: str
    task_stream_low: str
    consumer_group: str
    leader_lock: str
    scheduled_set: str


@dataclass(frozen=True)
class TaskKeys:
    """Container for all Redis keys related to a specific task.

    This immutable dataclass holds all the Redis keys needed for a single task's
    operation. Using a frozen dataclass ensures keys cannot be accidentally modified
    after creation and allows TaskKeys instances to be used as dictionary keys or
    in sets if needed.

    Attributes:
        next_run: Key storing the timestamp of the next scheduled execution.
            Used by the coordinator to determine when a task should be triggered.
        disabled: Key storing a flag that indicates whether the task is paused.
            When set, the coordinator will skip scheduling of this task.
        runs: Key for a Redis list containing the history of execution timestamps.
            Used for statistics and monitoring purposes.
        durations_second: Key for a Redis list containing the history of execution
            durations in seconds. Used for performance monitoring and statistics.
        retry_after: Key storing the Unix timestamp after which the task can be
            re-executed. When present and > now, the Coordinator skips scheduling.
        retry_delay: Key storing the current backoff delay in seconds. Used to
            calculate the next delay on consecutive failures. Reset on success.
    """

    next_run: str
    disabled: str
    runs: str
    durations_second: str
    retry_after: str
    retry_delay: str


class RedisKeyBuilder:
    """Centralized builder for Redis keys.

    This class provides a single point of control for constructing all Redis keys
    used by the task manager. Centralizing key construction ensures consistency
    across the codebase and makes it easier to modify the key pattern if needed.

    All keys follow the pattern: {prefix}_{group}_{task}_{suffix}

    Example:
        >>> builder = RedisKeyBuilder("myapp")
        >>> keys = builder.get_task_keys("notifications", "send_emails")
        >>> print(keys.next_run)
        myapp_notifications_send_emails_next_run

    Attributes:
        _prefix: The application-wide prefix for all Redis keys. This should
            match the redis_key_prefix from the Config object.
    """

    def __init__(self, prefix: str) -> None:
        """Initialize the RedisKeyBuilder with a prefix.

        Args:
            prefix: The application-wide prefix for all Redis keys.
                This is typically set via Config.redis_key_prefix and
                should be unique per application to avoid key collisions
                when multiple applications share the same Redis instance.
        """
        self._prefix = prefix

    @property
    def prefix(self) -> str:
        """Get the current prefix used for key construction.

        Returns:
            The prefix string used as the first component of all keys.
        """
        return self._prefix

    def _build_key(self, group: str, task: str, suffix: str) -> str:
        """Build a Redis key with the standard pattern.

        This is the core method that constructs keys following the
        {prefix}_{group}_{task}_{suffix} pattern. All other key-building
        methods delegate to this one to ensure consistency.

        Args:
            group: The task group name (e.g., "notifications", "cleanup").
            task: The individual task name (typically the function name).
            suffix: The key type identifier (e.g., "next_run", "disabled").

        Returns:
            A fully qualified Redis key string.
        """
        return f"{self._prefix}_{group}_{task}_{suffix}"

    def get_task_keys(self, group: str, task: str) -> TaskKeys:
        """Get all keys for a specific task.

        This method returns a TaskKeys object containing all Redis keys
        needed for a task's operation. Use this when you need multiple
        keys for the same task to avoid redundant string building.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            A TaskKeys dataclass containing all keys for the specified task.

        Example:
            >>> builder = RedisKeyBuilder("app")
            >>> keys = builder.get_task_keys("daily", "cleanup")
            >>> # Access individual keys from the container
            >>> await redis.get(keys.next_run)
            >>> await redis.get(keys.disabled)
        """
        return TaskKeys(
            next_run=self._build_key(group, task, "next_run"),
            disabled=self._build_key(group, task, "disabled"),
            runs=self._build_key(group, task, "runs"),
            durations_second=self._build_key(group, task, "durations_second"),
            retry_after=self._build_key(group, task, "retry_after"),
            retry_delay=self._build_key(group, task, "retry_delay"),
        )

    # =========================================================================
    # Convenience methods for individual keys
    # These methods are useful when only a single key is needed, avoiding
    # the overhead of creating a full TaskKeys object.
    # =========================================================================

    def next_run_key(self, group: str, task: str) -> str:
        """Build the key for storing the next run timestamp.

        This key stores the Unix timestamp of when the task should next execute.
        The runner checks this value to determine if a task is due for execution.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            The Redis key for the next run timestamp.
        """
        return self._build_key(group, task, "next_run")

    def disabled_key(self, group: str, task: str) -> str:
        """Build the key for the disabled flag.

        This key indicates whether a task is currently paused. When this key
        exists and contains a truthy value, the runner will skip execution
        of the associated task.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            The Redis key for the disabled flag.
        """
        return self._build_key(group, task, "disabled")

    def runs_key(self, group: str, task: str) -> str:
        """Build the key for the execution history list.

        This key stores a Redis list of timestamps representing when the task
        was executed. The list is capped at Config.statistics_history_runs entries
        to limit memory usage.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            The Redis key for the runs history list.
        """
        return self._build_key(group, task, "runs")

    def durations_key(self, group: str, task: str) -> str:
        """Build the key for the execution durations list.

        This key stores a Redis list of execution durations in seconds.
        Each entry corresponds to how long a task execution took.
        The list is capped at Config.statistics_history_runs entries.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            The Redis key for the durations history list.
        """
        return self._build_key(group, task, "durations_second")

    # =========================================================================
    # Stream-related keys
    # These methods provide keys for Redis Streams operation mode, including
    # the task stream, consumer group, and leader election.
    # =========================================================================

    def get_stream_keys(self) -> StreamKeys:
        """Get all keys related to Redis Streams operation.

        Returns a StreamKeys object containing the dual task stream keys
        (high/low priority), consumer group name, and leader lock key.
        Use this when operating in stream mode to get all necessary keys at once.

        Returns:
            A StreamKeys dataclass containing all stream-related keys.

        Example:
            >>> builder = RedisKeyBuilder("myapp")
            >>> stream_keys = builder.get_stream_keys()
            >>> print(stream_keys.task_stream_high)
            myapp_task_stream_high
        """
        return StreamKeys(
            task_stream_high=f"{self._prefix}_task_stream_high",
            task_stream_low=f"{self._prefix}_task_stream_low",
            consumer_group=f"{self._prefix}_workers",
            leader_lock=f"{self._prefix}_leader_lock",
            scheduled_set=f"{self._prefix}_scheduled_tasks",
        )

    def leader_lock_key(self) -> str:
        """Build the key for leader election lock.

        This key is used for distributed leader election. Only one worker
        can hold this lock at a time, and the lock holder becomes the leader
        responsible for scheduling tasks to the stream.

        Returns:
            The Redis key for the leader election lock.
        """
        return f"{self._prefix}_leader_lock"

    def task_stream_high_key(self) -> str:
        """Build the key for the high priority task stream.

        This key identifies the Redis Stream where high priority tasks are
        published by the leader. High priority tasks are always consumed first.

        Returns:
            The Redis key for the high priority task stream.
        """
        return f"{self._prefix}_task_stream_high"

    def task_stream_low_key(self) -> str:
        """Build the key for the low priority task stream.

        This key identifies the Redis Stream where low priority tasks are
        published by the leader. Low priority tasks are only consumed when
        workers have available capacity (semaphore slots).

        Returns:
            The Redis key for the low priority task stream.
        """
        return f"{self._prefix}_task_stream_low"

    def consumer_group_name(self) -> str:
        """Get the consumer group name for task workers.

        This is the name used when creating and joining the consumer group
        for the task stream. All workers in the same deployment should use
        the same consumer group name.

        Returns:
            The consumer group name.
        """
        return f"{self._prefix}_workers"

    # =========================================================================
    # Reconciliation-related keys
    # These methods provide keys for the reconciliation system, including
    # the scheduled task tracking set and per-task running indicators.
    # =========================================================================

    def scheduled_set_key(self) -> str:
        """Build the key for the SET tracking currently scheduled tasks.

        This Redis SET contains task identifiers (format: "group:task") for tasks
        that have been published to a stream but not yet completed. The Reconciler
        uses this to detect tasks that were lost (e.g., due to a leader crash
        before XADD, or a consumer crash before XACK).

        Returns:
            The Redis key for the scheduled tasks SET.
        """
        return f"{self._prefix}_scheduled_tasks"

    def dynamic_tasks_key(self) -> str:
        """Build the key for the Hash storing dynamic task definitions.

        This Redis Hash persists dynamic task definitions so they survive
        application restarts. Each field is a "{group}:{task_name}" identifier
        and the value is the JSON-serialized task definition.

        Returns:
            The Redis key for the dynamic tasks Hash.
        """
        return f"{self._prefix}_dynamic_tasks"

    def running_task_key(self, group: str, task: str) -> str:
        """Build the key indicating a task is currently being executed.

        This key is SET with a short TTL and renewed via heartbeat while the task
        runs. If the worker crashes, the key expires, signaling that the task is
        no longer being executed. The Reconciler checks this key to distinguish
        between "still running" and "worker crashed" scenarios.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            The Redis key for the running task indicator.
        """
        return f"{self._prefix}_{group}_{task}_running"
