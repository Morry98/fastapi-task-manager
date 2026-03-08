"""Service layer for task router API endpoints.

This module provides async service functions for managing tasks via the REST API.
It handles task retrieval, enabling/disabling, triggering, statistics management,
health checks and configuration inspection using the shared async Redis connection.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi.exceptions import HTTPException

from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.health import ConfigResponse, HealthResponse
from fastapi_task_manager.schema.task import AffectedTask, Task, TaskActionResponse, TaskDetailed, TaskRun
from fastapi_task_manager.schema.task_group import TaskGroup as TaskGroupSchema

if TYPE_CHECKING:
    from fastapi_task_manager.task_group import TaskGroup
    from fastapi_task_manager.task_manager import TaskManager


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _find_tasks(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    name: str | None = None,
    tag: str | None = None,
) -> list[tuple["TaskGroup", Task]]:
    """Find all tasks matching the given filters.

    Returns a list of (TaskGroup, Task) pairs for every match.
    Raises 404 if nothing matches.
    """
    matches: list[tuple[TaskGroup, Task]] = []

    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if name is not None and name != t.name:
                continue
            if tag is not None and t.tags is not None and tag not in t.tags:
                continue
            matches.append((tg, t))

    if not matches:
        raise HTTPException(status_code=404, detail="No matching tasks found")

    return matches


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


def get_task_groups(
    task_manager: "TaskManager",
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskGroupSchema]:
    """Retrieve task groups with optional filtering.

    Returns group metadata including task count.
    """
    return [
        TaskGroupSchema(
            name=x.name,
            tags=x.tags,
            task_count=len(x.tasks),
        )
        for x in task_manager.task_groups
        if (name is None or name == x.name) and (tag is None or tag in x.tags)
    ]


async def get_tasks(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskDetailed]:
    """Retrieve detailed task information with statistics from Redis.

    Uses the shared async Redis connection and pipelines for efficient batch reads.
    Includes running state detection for both polling and stream modes.
    """
    redis_client = task_manager.redis_client
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    list_to_return: list[TaskDetailed] = []

    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue

        for t in tg.tasks:
            if (name is not None and name != t.name) or (tag is not None and t.tags is not None and tag not in t.tags):
                continue

            keys = key_builder.get_task_keys(tg.name, t.name)

            # Build async pipeline with all reads for this task
            pipe = redis_client.pipeline()
            pipe.lrange(keys.runs, 0, -1)
            pipe.lrange(keys.durations_second, 0, -1)
            pipe.get(keys.next_run)
            pipe.get(keys.disabled)
            pipe.get(keys.retry_after)
            pipe.get(keys.retry_delay)

            # Check running state via heartbeat key
            running_key = key_builder.running_task_key(tg.name, t.name)
            pipe.exists(running_key)

            results = await pipe.execute()

            # Unpack pipeline results
            runs_raw: list[bytes] = results[0]
            durations_raw: list[bytes] = results[1]
            next_run_b: bytes | None = results[2]
            disabled_b: bytes | None = results[3]
            retry_after_b: bytes | None = results[4]
            retry_delay_b: bytes | None = results[5]
            is_running: bool = bool(results[6])

            # Runs and durations are stored via LPUSH (newest first) - reverse to chronological
            runs: list[float] = [float(r) for r in runs_raw[::-1]] if runs_raw else []
            durations: list[float] = [float(d) for d in durations_raw[::-1]] if durations_raw else []

            # Truncate to paired data if inconsistent
            if len(runs) != len(durations):
                min_length = min(len(runs), len(durations))
                runs = runs[:min_length]
                durations = durations[:min_length]

            # Parse next run timestamp (sentinel value = year 2000 = never scheduled)
            next_run = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
            if next_run_b is not None:
                next_run = datetime.fromtimestamp(float(next_run_b.decode("utf-8")), tz=timezone.utc)

            is_active = disabled_b is None

            retry_after = None
            if retry_after_b is not None:
                retry_after = datetime.fromtimestamp(float(retry_after_b.decode("utf-8")), tz=timezone.utc)
            retry_delay = float(retry_delay_b.decode("utf-8")) if retry_delay_b is not None else None

            list_to_return.append(
                TaskDetailed(
                    name=t.name,
                    description=t.description,
                    tags=t.tags,
                    expression=t.expression,
                    high_priority=t.high_priority,
                    task_group_name=tg.name,
                    next_run=next_run,
                    is_active=is_active,
                    is_running=is_running,
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


# ---------------------------------------------------------------------------
# POST action endpoints (bulk)
# ---------------------------------------------------------------------------


async def disable_tasks(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> TaskActionResponse:
    """Disable all matching tasks. Sets a disabled flag in Redis.

    When disabled, the runner/coordinator skips execution.
    Operates on ALL matching tasks (bulk).
    """
    matches = _find_tasks(task_manager, task_group_name, task_name, tag)
    redis_client = task_manager.redis_client
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    affected: list[AffectedTask] = []
    for tg, t in matches:
        keys = key_builder.get_task_keys(tg.name, t.name)
        await redis_client.set(
            keys.disabled,
            "1",
            ex=task_manager.config.statistics_redis_expiration,
        )
        affected.append(AffectedTask(task_group=tg.name, task=t.name))

    return TaskActionResponse(affected_tasks=affected, count=len(affected))


async def enable_tasks(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> TaskActionResponse:
    """Enable all matching tasks. Removes the disabled flag from Redis.

    Operates on ALL matching tasks (bulk).
    """
    matches = _find_tasks(task_manager, task_group_name, task_name, tag)
    redis_client = task_manager.redis_client
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    affected: list[AffectedTask] = []
    for tg, t in matches:
        keys = key_builder.get_task_keys(tg.name, t.name)
        await redis_client.delete(keys.disabled)
        affected.append(AffectedTask(task_group=tg.name, task=t.name))

    return TaskActionResponse(affected_tasks=affected, count=len(affected))


async def reset_retry(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> TaskActionResponse:
    """Reset the backoff state for all matching tasks.

    Removes retry_after and retry_delay keys, allowing immediate re-scheduling.
    Operates on ALL matching tasks (bulk).
    """
    matches = _find_tasks(task_manager, task_group_name, task_name, tag)
    redis_client = task_manager.redis_client
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    affected: list[AffectedTask] = []
    for tg, t in matches:
        keys = key_builder.get_task_keys(tg.name, t.name)
        await redis_client.delete(keys.retry_after, keys.retry_delay)
        affected.append(AffectedTask(task_group=tg.name, task=t.name))

    return TaskActionResponse(affected_tasks=affected, count=len(affected))


async def trigger_tasks(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> TaskActionResponse:
    """Trigger immediate execution of all matching tasks.

    Sets next_run to epoch 0 so the runner/coordinator picks them up
    on the next cycle. Also clears retry backoff if present.
    Operates on ALL matching tasks (bulk).
    """
    matches = _find_tasks(task_manager, task_group_name, task_name, tag)
    redis_client = task_manager.redis_client
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    affected: list[AffectedTask] = []
    for tg, t in matches:
        keys = key_builder.get_task_keys(tg.name, t.name)
        pipe = redis_client.pipeline()
        # Set next_run to epoch 0 to force immediate scheduling
        pipe.set(keys.next_run, "0")
        # Also clear any active backoff that would block scheduling
        pipe.delete(keys.retry_after, keys.retry_delay)
        await pipe.execute()
        affected.append(AffectedTask(task_group=tg.name, task=t.name))

    return TaskActionResponse(affected_tasks=affected, count=len(affected))


async def clear_statistics(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
) -> TaskActionResponse:
    """Clear execution history (runs and durations) for all matching tasks.

    Operates on ALL matching tasks (bulk).
    """
    matches = _find_tasks(task_manager, task_group_name, task_name, tag)
    redis_client = task_manager.redis_client
    key_builder = RedisKeyBuilder(task_manager.config.redis_key_prefix)

    affected: list[AffectedTask] = []
    for tg, t in matches:
        keys = key_builder.get_task_keys(tg.name, t.name)
        await redis_client.delete(keys.runs, keys.durations_second)
        affected.append(AffectedTask(task_group=tg.name, task=t.name))

    return TaskActionResponse(affected_tasks=affected, count=len(affected))


# ---------------------------------------------------------------------------
# Health & config endpoints
# ---------------------------------------------------------------------------


async def get_health(task_manager: "TaskManager") -> HealthResponse:
    """Return system health: runner status, Redis connectivity, worker info."""
    runner = task_manager.runner

    # Check Redis connectivity
    redis_connected = False
    if task_manager.redis_client is not None:
        try:
            redis_connected = bool(await task_manager.redis_client.ping())  # ty: ignore[invalid-await]
        except Exception:
            redis_connected = False

    # Determine status - runner must be alive and Redis reachable
    is_running = runner is not None
    status = "healthy" if is_running and redis_connected else "unhealthy"

    # Worker and leader info (only available when runner is active)
    worker_id: str | None = None
    worker_started_at: str | None = None
    is_leader: bool | None = None

    if runner is not None:
        worker_id = runner.worker_id
        worker_started_at = runner.worker_started_at
        is_leader = runner.is_leader

    return HealthResponse(
        status=status,
        redis_connected=redis_connected,
        worker_id=worker_id,
        worker_started_at=worker_started_at,
        is_leader=is_leader,
    )


def get_config(task_manager: "TaskManager") -> ConfigResponse:
    """Return the current operational configuration (no secrets)."""
    c = task_manager.config
    return ConfigResponse(
        redis_key_prefix=c.redis_key_prefix,
        concurrent_tasks=c.concurrent_tasks,
        statistics_history_runs=c.statistics_history_runs,
        statistics_redis_expiration=c.statistics_redis_expiration,
        poll_interval=c.poll_interval,
        initial_lock_ttl=c.initial_lock_ttl,
        worker_service_name=c.worker_service_name,
        stream_max_len=c.stream_max_len,
        stream_block_ms=c.stream_block_ms,
        leader_lock_ttl=c.leader_lock_ttl,
        leader_heartbeat_interval=c.leader_heartbeat_interval,
        leader_retry_interval=c.leader_retry_interval,
        reconciliation_enabled=c.reconciliation_enabled,
        reconciliation_interval=c.reconciliation_interval,
        reconciliation_overdue_seconds=c.reconciliation_overdue_seconds,
        pending_message_timeout_ms=c.pending_message_timeout_ms,
        retry_backoff=c.retry_backoff,
        retry_backoff_max=c.retry_backoff_max,
        retry_backoff_multiplier=c.retry_backoff_multiplier,
        retry_key_ttl=c.retry_key_ttl,
        running_heartbeat_ttl=c.running_heartbeat_ttl,
        running_heartbeat_interval=c.running_heartbeat_interval,
    )
