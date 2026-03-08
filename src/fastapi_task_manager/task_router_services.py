"""Service layer for task router API endpoints.

This module provides service functions for managing tasks via the REST API.
It handles task retrieval, enabling/disabling, and statistics collection
using Redis as the backend store.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi.exceptions import HTTPException
from redis.client import Redis

from fastapi_task_manager import TaskGroup
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import Task, TaskDetailed, TaskRun

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager


def get_task_groups(
    task_manager: "TaskManager",
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskGroup]:
    """Retrieve task groups with optional filtering.

    Args:
        task_manager: The TaskManager instance containing all task groups.
        name: Optional filter to match task group name exactly.
        tag: Optional filter to match task groups containing this tag.

    Returns:
        A list of TaskGroup objects matching the filter criteria.
    """
    return [
        TaskGroup(
            name=x.name,
            tags=x.tags,
        )
        for x in task_manager.task_groups
        if (name is None or name == x.name) and (tag is None or tag in x.tags)
    ]


def get_tasks(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskDetailed]:
    """Retrieve detailed task information with statistics from Redis.

    This function fetches task metadata along with execution statistics
    (run history, durations, next scheduled run) from Redis. It uses
    Redis pipelines to batch multiple read operations and reduce
    network round-trips.

    Args:
        task_manager: The TaskManager instance containing all task groups.
        task_group_name: Optional filter for a specific task group.
        name: Optional filter to match task name exactly.
        tag: Optional filter to match tasks containing this tag.

    Returns:
        A list of TaskDetailed objects with full statistics.
    """
    list_to_return = []

    # Create Redis client connection
    redis_client = Redis(
        host=task_manager.config.redis_host,
        port=task_manager.config.redis_port,
        password=task_manager.config.redis_password,
        db=task_manager.config.redis_db,
    )

    # Create key builder for centralized key construction
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    for tg in task_manager.task_groups:
        # Skip task groups that don't match the filter
        if task_group_name is not None and task_group_name != tg.name:
            continue

        for t in tg.tasks:
            # Skip tasks that don't match the name or tag filters
            if (name is not None and name != t.name) or (tag is not None and t.tags is not None and tag not in t.tags):
                continue

            # Get all Redis keys for this task using the centralized key builder
            keys = key_builder.get_task_keys(tg.name, t.name)

            # Use a pipeline to batch all Redis read operations for this task
            pipe = redis_client.pipeline()
            pipe.lrange(keys.runs, 0, -1)  # Get all run timestamps from the list
            pipe.lrange(keys.durations_second, 0, -1)  # Get all durations from the list
            pipe.get(keys.next_run)  # Get next scheduled run timestamp
            pipe.get(keys.disabled)  # Check if task is disabled
            pipe.get(keys.retry_after)  # Get retry backoff timestamp
            pipe.get(keys.retry_delay)  # Get current backoff delay
            results = pipe.execute()

            # Unpack pipeline results
            runs_raw: list[bytes] = results[0]
            durations_raw: list[bytes] = results[1]
            next_run_b: bytes | None = results[2]
            disabled_b: bytes | None = results[3]
            retry_after_b: bytes | None = results[4]
            retry_delay_b: bytes | None = results[5]

            # Convert runs from bytes to floats
            # Redis Lists with LPUSH store items in reverse order (newest first)
            # We reverse to get chronological order (oldest first)
            runs: list[float] = [float(r) for r in runs_raw[::-1]] if runs_raw else []

            # Convert durations from bytes to floats (same reverse logic)
            durations: list[float] = [float(d) for d in durations_raw[::-1]] if durations_raw else []

            # Handle potential data inconsistency between runs and durations
            # Truncate to the minimum length to ensure paired data
            if len(runs) != len(durations):
                min_length = min(len(runs), len(durations))
                runs = runs[:min_length]
                durations = durations[:min_length]

            # Parse next run timestamp (use default if not set)
            # Default to year 2000 as a sentinel value indicating "never scheduled"
            next_run = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
            if next_run_b is not None:
                next_run = datetime.fromtimestamp(float(next_run_b.decode("utf-8")), tz=timezone.utc)

            # Determine if task is active (not disabled)
            # A task is disabled if the disabled key exists (has any value)
            is_active = disabled_b is None

            # Parse retry backoff state (None if no backoff active)
            retry_after = None
            if retry_after_b is not None:
                retry_after = datetime.fromtimestamp(
                    float(retry_after_b.decode("utf-8")),
                    tz=timezone.utc,
                )
            retry_delay = float(retry_delay_b.decode("utf-8")) if retry_delay_b is not None else None

            # Build the detailed task response with run history
            list_to_return.append(
                TaskDetailed(
                    name=t.name,
                    description=t.description,
                    tags=t.tags,
                    expression=t.expression,
                    high_priority=t.high_priority,
                    next_run=next_run,
                    is_active=is_active,
                    retry_after=retry_after,
                    retry_delay=retry_delay,
                    runs=[
                        TaskRun(
                            run_date=datetime.fromtimestamp(runs[i], timezone.utc),
                            durations_second=durations[i],
                        )
                        for i in range(len(runs))
                    ],
                ),
            )

    return list_to_return


def disable_task(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> None:
    """Disable a task to prevent its execution.

    Sets a disabled flag in Redis for the matching task. When disabled,
    the runner will skip execution of this task until it is re-enabled.

    Args:
        task_manager: The TaskManager instance containing all task groups.
        task_group_name: Optional filter for a specific task group.
        task_name: Optional filter to match task name exactly.
        tag: Optional filter to match tasks containing this tag.

    Raises:
        HTTPException: 404 error if no matching task is found.
    """
    # Find the matching task
    task: Task | None = None
    task_group: TaskGroup | None = None

    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if (task_name is not None and task_name != t.name) or (
                tag is not None and t.tags is not None and tag not in t.tags
            ):
                continue
            task = t
            task_group = tg
            break

    if task is None or task_group is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Create Redis client connection
    redis_client = Redis(
        host=task_manager.config.redis_host,
        port=task_manager.config.redis_port,
        password=task_manager.config.redis_password,
        db=task_manager.config.redis_db,
    )

    # Use key builder for centralized key construction
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)
    keys = key_builder.get_task_keys(task_group.name, task.name)

    # Set the disabled flag with expiration
    # The flag value "1" is arbitrary; presence of the key indicates disabled state
    redis_client.set(
        keys.disabled,
        "1",
        ex=task_manager.config.statistics_redis_expiration,
    )


def reset_retry(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> None:
    """Reset the backoff state for a task, allowing immediate re-execution.

    Removes the retry_after and retry_delay keys from Redis, clearing any
    active backoff. The task will be scheduled normally on the next cron tick.

    Args:
        task_manager: The TaskManager instance containing all task groups.
        task_group_name: Optional filter for a specific task group.
        task_name: Optional filter to match task name exactly.
        tag: Optional filter to match tasks containing this tag.

    Raises:
        HTTPException: 404 error if no matching task is found.
    """
    # Find the matching task
    task: Task | None = None
    task_group: TaskGroup | None = None

    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if (task_name is not None and task_name != t.name) or (
                tag is not None and t.tags is not None and tag not in t.tags
            ):
                continue
            task = t
            task_group = tg
            break

    if task is None or task_group is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Create Redis client connection
    redis_client = Redis(
        host=task_manager.config.redis_host,
        port=task_manager.config.redis_port,
        password=task_manager.config.redis_password,
        db=task_manager.config.redis_db,
    )

    # Use key builder for centralized key construction
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)
    keys = key_builder.get_task_keys(task_group.name, task.name)

    # Delete both retry keys to clear the backoff state
    redis_client.delete(keys.retry_after, keys.retry_delay)


def enable_task(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> None:
    """Enable a previously disabled task.

    Removes the disabled flag from Redis for the matching task,
    allowing the runner to execute it according to its schedule.

    Args:
        task_manager: The TaskManager instance containing all task groups.
        task_group_name: Optional filter for a specific task group.
        task_name: Optional filter to match task name exactly.
        tag: Optional filter to match tasks containing this tag.

    Raises:
        HTTPException: 404 error if no matching task is found.
    """
    # Find the matching task
    task: Task | None = None
    task_group: TaskGroup | None = None

    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if (task_name is not None and task_name != t.name) or (
                tag is not None and t.tags is not None and tag not in t.tags
            ):
                continue
            task = t
            task_group = tg
            break

    if task is None or task_group is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Create Redis client connection
    redis_client = Redis(
        host=task_manager.config.redis_host,
        port=task_manager.config.redis_port,
        password=task_manager.config.redis_password,
        db=task_manager.config.redis_db,
    )

    # Use key builder for centralized key construction
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)
    keys = key_builder.get_task_keys(task_group.name, task.name)

    # Delete the disabled key directly (no need to check EXISTS first)
    # Redis DELETE is idempotent - safe to call even if key doesn't exist
    redis_client.delete(keys.disabled)
