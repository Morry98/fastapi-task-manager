"""Integration tests for behaviours that work today (safety net).

Each test runs one or more TaskManager instances against a real Redis server
and checks an end-to-end guarantee: a triggered task runs once, cron
scheduling advances next_run, a single leader is elected, leadership fails
over, and the consumer survives the loss of its consumer group.
"""

import asyncio
import time
from datetime import datetime, timezone

import pytest
from cronsim import CronSim
from redis.asyncio import Redis

from fastapi_task_manager import TaskGroup
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.task_router_services import trigger_tasks
from tests.integration.conftest import (
    YEARLY_CRON,
    ManagerFactory,
    seed_next_run_far_future,
    task_name,
    wait_for_leader,
    wait_until,
)

pytestmark = pytest.mark.integration


def _counting_group(calls: list[str], label: str, expr: str = YEARLY_CRON, **task_options) -> TaskGroup:
    """Build a group "g" with one task "probe" that appends ``label`` to ``calls`` when it runs.

    Each TaskManager instance needs its own TaskGroup object; building them
    with the same group name, task name and cron gives every instance the
    same internal task name, exactly like replicas of the same application.
    """
    group = TaskGroup(name="g")

    @group.add_task(expr, name="probe", **task_options)
    async def probe() -> None:
        calls.append(label)

    return group


async def test_triggered_task_runs_exactly_once(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    """A triggered task runs once, records statistics and clears its runtime keys."""
    calls: list[str] = []
    group = _counting_group(calls, "A")
    name = task_name(group, "probe")
    await seed_next_run_far_future(redis, keys, "g", name)

    manager = await make_manager([group])
    await wait_for_leader([manager])
    await trigger_tasks(manager, task_group_name="g", task_name=name)

    assert await wait_until(lambda: len(calls) >= 1, timeout=5), "triggered task never ran"
    # Several coordinator cycles: a duplicate publish would show up here.
    await wait_until(lambda: len(calls) > 1, timeout=1)
    assert calls == ["A"]

    # Success path side effects: one stats entry, no running key, not tracked as scheduled.
    # The consumer records stats, deletes the running key, then removes the
    # scheduled-set member, in this order, once the task returns.
    stats_key = keys.stats_stream_key("g", name)

    async def tracking_cleared() -> bool:
        if await redis.xlen(stats_key) < 1:
            return False
        still_scheduled = await redis.sismember(keys.scheduled_set_key(), f"g:{name}")  # ty: ignore[invalid-await]
        return not still_scheduled

    assert await wait_until(tracking_cleared, timeout=2), "success path did not record stats and clear tracking"
    assert await redis.xlen(stats_key) == 1
    # Checked right away: the running key also has a TTL (2 s), so waiting
    # for it to disappear would pass even if the consumer never deleted it.
    assert not await redis.exists(keys.running_task_key("g", name)), "running key left behind after success"


async def test_cron_task_runs_when_due_and_schedules_next_occurrence(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    """A task whose next_run comes due runs once and next_run moves to the next cron occurrence."""
    calls: list[str] = []
    # Yearly cron: the next occurrence can never come due inside the test window
    # (a per-minute cron would legitimately run again when the test crosses a minute).
    group = _counting_group(calls, "A")
    name = task_name(group, "probe")
    next_run_key = keys.next_run_key("g", name)
    # Due one second from now.
    seeded = time.time() + 1
    await redis.set(next_run_key, seeded)

    manager = await make_manager([group])
    await wait_for_leader([manager])

    assert await wait_until(lambda: len(calls) >= 1, timeout=5), "due task never ran"
    await wait_until(lambda: len(calls) > 1, timeout=1)
    assert calls == ["A"]

    # The coordinator stores the next cron occurrence as the new next_run (just after publishing).
    async def next_run_updated() -> bool:
        return float(await redis.get(next_run_key) or 0) != seeded

    assert await wait_until(next_run_updated, timeout=2), "next_run was never updated"
    next_run = float(await redis.get(next_run_key))
    expected = next(CronSim(YEARLY_CRON, datetime.now(timezone.utc))).timestamp()
    assert next_run == expected


async def test_only_one_instance_becomes_leader(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    """With two instances on the same Redis only one holds the leader lock."""
    first = await make_manager([TaskGroup(name="g")])
    leader = await wait_for_leader([first])
    second = await make_manager([TaskGroup(name="g")])

    # Give the second instance several acquisition attempts (retry interval 0.2 s).
    both_leaders = await wait_until(
        lambda: (
            first.runner is not None
            and second.runner is not None
            and first.runner.is_leader
            and second.runner.is_leader
        ),
        timeout=1.5,
    )
    assert not both_leaders, "two instances believe they are leader at the same time"
    assert leader is first
    assert second.runner is not None
    assert not second.runner.is_leader

    # The lock is held by the leader's worker id.
    lock_owner = await redis.get(keys.leader_lock_key())
    assert lock_owner is not None
    assert first.runner is not None
    assert first.runner.worker_id.split("-")[-1] in lock_owner


async def test_instance_that_is_not_leader_never_schedules(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    """A follower leaves due tasks alone: only the lock holder publishes them."""
    # Another (fake) worker holds the leader lock for the whole test.
    await redis.set(keys.leader_lock_key(), "another-worker", ex=60)

    calls: list[str] = []
    group = _counting_group(calls, "A")
    name = task_name(group, "probe")
    next_run_key = keys.next_run_key("g", name)
    # The task is overdue: a leader would publish it on its next cycle.
    await redis.set(next_run_key, "0")

    manager = await make_manager([group])

    # Many coordinator and acquisition cycles (retry interval 0.2 s).
    published = await wait_until(lambda: _next_run_changed(redis, next_run_key), timeout=1.5)
    assert not published, "an instance that is not leader rescheduled the task"
    assert calls == []
    assert manager.runner is not None
    assert not manager.runner.is_leader


async def _next_run_changed(redis: Redis, next_run_key: str) -> bool:
    """True when next_run no longer holds the "0" seeded by the test."""
    return await redis.get(next_run_key) != "0"


async def test_leadership_fails_over_when_leader_stops(make_manager: ManagerFactory) -> None:
    """When the leader stops, the remaining instance takes over."""
    first = await make_manager([TaskGroup(name="g")])
    await wait_for_leader([first])
    second = await make_manager([TaskGroup(name="g")])

    await first.stop()

    assert await wait_until(
        lambda: second.runner is not None and second.runner.is_leader,
        timeout=5,
    ), "the surviving instance never became leader"


async def test_triggered_task_runs_once_across_instances(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    """With two instances, a triggered task runs on exactly one of them, once."""
    calls: list[str] = []
    group_a = _counting_group(calls, "A")
    group_b = _counting_group(calls, "B")
    name = task_name(group_a, "probe")
    await seed_next_run_far_future(redis, keys, "g", name)

    first = await make_manager([group_a])
    await wait_for_leader([first])
    second = await make_manager([group_b])
    await wait_for_leader([first, second])

    await trigger_tasks(first, task_group_name="g", task_name=name)

    assert await wait_until(lambda: len(calls) >= 1, timeout=5), "triggered task never ran"
    await wait_until(lambda: len(calls) > 1, timeout=1.5)
    assert len(calls) == 1, f"task ran {len(calls)} times: {calls}"


async def test_allow_parallel_false_waits_for_running_execution(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
    release: asyncio.Event,
) -> None:
    """With allow_parallel=False a second trigger waits until the running execution ends."""
    starts: list[float] = []
    running = 0
    max_running = 0
    group = TaskGroup(name="g")

    @group.add_task(YEARLY_CRON, name="probe", allow_parallel=False)
    async def probe() -> None:
        nonlocal running, max_running
        starts.append(time.monotonic())
        running += 1
        max_running = max(max_running, running)
        try:
            # Stay busy until the test releases the task (bounded as a safety net).
            await asyncio.wait_for(release.wait(), timeout=10)
        finally:
            running -= 1

    name = task_name(group, "probe")
    await seed_next_run_far_future(redis, keys, "g", name)
    manager = await make_manager([group])
    await wait_for_leader([manager])

    await trigger_tasks(manager, task_group_name="g", task_name=name)
    assert await wait_until(lambda: len(starts) == 1, timeout=5), "first execution never started"

    # Second trigger while the first execution is still running.
    await trigger_tasks(manager, task_group_name="g", task_name=name)
    started_again = await wait_until(lambda: len(starts) > 1, timeout=1)
    assert not started_again, "a second execution started while the first was running"

    # Once the first execution ends, the pending trigger is honoured.
    release.set()
    assert await wait_until(lambda: len(starts) == 2, timeout=5), "pending trigger never ran"
    assert max_running == 1


async def test_consumer_recovers_after_redis_keys_are_flushed(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    """Deleting every key of the app (as FLUSHALL does) must not stop task execution.

    Only the keys under the test prefix are deleted, which removes the streams
    and their consumer groups exactly like a flush, without touching other
    data on the server.
    """
    calls: list[str] = []
    group = _counting_group(calls, "A")
    name = task_name(group, "probe")
    await seed_next_run_far_future(redis, keys, "g", name)
    manager = await make_manager([group])
    await wait_for_leader([manager])

    # Simulate the flush.
    flushed = [key async for key in redis.scan_iter(match=f"{keys.prefix}*")]
    assert flushed
    await redis.delete(*flushed)

    # The consumer recreates its consumer group after hitting NOGROUP.
    async def group_exists() -> bool:
        try:
            groups = await redis.xinfo_groups(keys.task_stream_low_key())
        except Exception:
            return False
        return any(g["name"] == keys.consumer_group_name() for g in groups)

    assert await wait_until(group_exists, timeout=5), "consumer group was never recreated"
    assert await wait_until(lambda: manager.runner is not None and manager.runner.is_leader, timeout=5)

    # Right after the flush the coordinator may publish the task once on its own
    # (next_run is gone). Push next_run away again and count from here, so the
    # assertion below needs a message published after the consumer recovered.
    await seed_next_run_far_future(redis, keys, "g", name)
    runs_before_trigger = len(calls)

    # A task triggered after the flush still runs.
    await trigger_tasks(manager, task_group_name="g", task_name=name)
    assert await wait_until(lambda: len(calls) > runs_before_trigger, timeout=5), "task never ran after the flush"
