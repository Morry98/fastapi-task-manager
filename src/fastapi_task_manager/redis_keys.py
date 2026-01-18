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
    - suffix: Key type identifier (next_run, runner_uuid, etc.)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskKeys:
    """Container for all Redis keys related to a specific task.

    This immutable dataclass holds all the Redis keys needed for a single task's
    operation. Using a frozen dataclass ensures keys cannot be accidentally modified
    after creation and allows TaskKeys instances to be used as dictionary keys or
    in sets if needed.

    Attributes:
        next_run: Key storing the timestamp of the next scheduled execution.
            Used by the runner to determine when a task should be triggered.
        runner_uuid: Key used as a distributed lock to ensure only one instance
            of the application executes a task at any given time. Contains the
            UUID of the runner that currently holds the lock.
        disabled: Key storing a flag that indicates whether the task is paused.
            When set, the runner will skip execution of this task.
        runs: Key for a Redis list containing the history of execution timestamps.
            Used for statistics and monitoring purposes.
        durations_second: Key for a Redis list containing the history of execution
            durations in seconds. Used for performance monitoring and statistics.
    """

    next_run: str
    runner_uuid: str
    disabled: str
    runs: str
    durations_second: str


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
            runner_uuid=self._build_key(group, task, "runner_uuid"),
            disabled=self._build_key(group, task, "disabled"),
            runs=self._build_key(group, task, "runs"),
            durations_second=self._build_key(group, task, "durations_second"),
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

    def runner_uuid_key(self, group: str, task: str) -> str:
        """Build the key for the runner UUID lock.

        This key implements distributed locking to ensure only one application
        instance executes a task at any given time. The value stored is the
        UUID of the runner that currently holds the lock.

        Args:
            group: The task group name.
            task: The individual task name.

        Returns:
            The Redis key for the runner UUID lock.
        """
        return self._build_key(group, task, "runner_uuid")

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
