"""Integration tests that document known bugs (one test per finding).

Every test here describes the CORRECT behaviour and currently fails because
of the bug named in its ``xfail`` reason. The markers are strict and only
accept an ``AssertionError``: when a fix lands, the test starts passing,
pytest reports it as XPASS(strict) and the build fails until the marker is
removed, which turns the scenario into a regression test. Any other error
(Redis down, a fixture failure, a crash) is reported as a real failure.
"""

import asyncio
import time

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis

from fastapi_task_manager import TaskGroup
from fastapi_task_manager.redis_keys import RedisKeyBuilder
from fastapi_task_manager.schema.task import CreateDynamicTaskRequest
from fastapi_task_manager.task_router_services import (
    create_dynamic_task,
    delete_dynamic_task,
    disable_tasks,
    get_tasks,
    trigger_tasks,
)
from tests.integration.conftest import (
    EVENTUALLY,
    YEARLY_CRON,
    ManagerFactory,
    require,
    seed_next_run_far_future,
    task_name,
    wait_for_leader,
    wait_until,
)

pytestmark = pytest.mark.integration


def known_bug(reason: str) -> pytest.MarkDecorator:
    """Strict xfail that only accepts the assertion describing the bug."""
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)


def _long_task_group(starts: list[float], release: asyncio.Event) -> TaskGroup:
    """Group "g" with a yearly, non-parallel task "long" that runs until ``release`` is set."""
    group = TaskGroup(name="g")

    @group.add_task(YEARLY_CRON, name="long", allow_parallel=False)
    async def long() -> None:
        starts.append(time.monotonic())
        # Bounded wait as a safety net: the fixture sets the event at teardown.
        await asyncio.wait_for(release.wait(), timeout=15)

    return group


# Stuck-message threshold = ceil(0.2 * 9) = 2 s, running key TTL = 1 s,
# renewed every 0.2 s: the running key never expires while the task runs.
# Reconciliation every second (it is off by default in the integration config).
LONG_TASK_TIMINGS = {"running_heartbeat_interval": 0.2, "reconciliation_interval": 1}

# Window in which a buggy behaviour that happens on its own (a duplicate start,
# a run at startup) is given the chance to show up. It starts only once the
# preconditions of the bug hold, so a slow machine cannot make the bug "vanish"
# and report a false XPASS.
BUG_WINDOW = 5.0


async def _pending_message_idle(redis: Redis, keys: RedisKeyBuilder) -> bool:
    """True when a pending message of the low priority stream is older than the 2 s stuck threshold."""
    pending = await redis.xpending_range(
        keys.task_stream_low_key(),
        keys.consumer_group_name(),
        min="-",
        max="+",
        count=10,
    )
    return any(entry["time_since_delivered"] > 2_100 for entry in pending)


# ---------------------------------------------------------------------------
# FTM-01: live long-running tasks are executed again
# ---------------------------------------------------------------------------


@known_bug(
    "FTM-01: the Reconciler requeues a pending message whose task is still running "
    "(it ignores the running key), so a long task starts again in parallel",
)
async def test_reconciler_does_not_restart_a_task_that_is_still_running(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
    release: asyncio.Event,
) -> None:
    starts: list[float] = []
    group = _long_task_group(starts, release)
    name = task_name(group, "long")
    await seed_next_run_far_future(redis, keys, "g", name)
    manager = await make_manager([group], **LONG_TASK_TIMINGS)
    await wait_for_leader([manager])

    await trigger_tasks(manager, task_group_name="g", task_name=name)
    require(await wait_until(lambda: len(starts) >= 1, timeout=EVENTUALLY), "task never started")

    # The task stays alive (heartbeat renewed). Wait until its pending message is
    # past the 2 s stuck threshold (or the Reconciler already acted on it), then
    # leave several 1 s reconciliation cycles for a duplicate start to appear.
    async def message_stuck_or_restarted() -> bool:
        return len(starts) > 1 or await _pending_message_idle(redis, keys)

    require(await wait_until(message_stuck_or_restarted, timeout=EVENTUALLY), "message never became idle")
    await wait_until(lambda: len(starts) > 1, timeout=BUG_WINDOW)
    assert len(starts) == 1, (
        f"FTM-01: a running task with allow_parallel=False was started {len(starts)} times, "
        f"at {[round(s - starts[0], 1) for s in starts]} s"
    )


@known_bug(
    "FTM-01: a starting instance claims (XAUTOCLAIM) the pending message of a task that is "
    "still running on another live instance and runs it again",
)
async def test_starting_instance_does_not_steal_a_running_task(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
    release: asyncio.Event,
) -> None:
    starts: list[float] = []
    # Reconciliation is pushed out of the test window: only startup recovery is exercised.
    timings = {**LONG_TASK_TIMINGS, "reconciliation_interval": 3600}
    group_a = _long_task_group(starts, release)
    name = task_name(group_a, "long")
    await seed_next_run_far_future(redis, keys, "g", name)
    first = await make_manager([group_a], **timings)
    await wait_for_leader([first])

    await trigger_tasks(first, task_group_name="g", task_name=name)
    require(await wait_until(lambda: len(starts) >= 1, timeout=EVENTUALLY), "task never started")

    # Wait until the pending message is older than the 2 s stuck threshold.
    require(
        await wait_until(lambda: _pending_message_idle(redis, keys), timeout=EVENTUALLY),
        "message never became idle",
    )

    # A new replica starts (rolling deploy / autoscaling) while the task is alive.
    await make_manager([_long_task_group(starts, release)], **timings)

    await wait_until(lambda: len(starts) > 1, timeout=BUG_WINDOW)
    assert len(starts) == 1, (
        f"FTM-01: a task still running on a live instance was started {len(starts)} times "
        "after another instance started"
    )


# ---------------------------------------------------------------------------
# FTM-02: dynamic tasks are not shared between instances
# ---------------------------------------------------------------------------


def _dynamic_group(calls: list[str], label: str) -> TaskGroup:
    """Group "g" exposing a registered function "work" for dynamic tasks."""
    group = TaskGroup(name="g")

    @group.register_function("work")
    async def work() -> None:
        calls.append(label)

    return group


@known_bug(
    "FTM-02: a dynamic task created through a follower is only known to that follower; the leader never schedules it",
)
async def test_dynamic_task_created_on_follower_runs(make_manager: ManagerFactory) -> None:
    calls: list[str] = []
    leader = await make_manager([_dynamic_group(calls, "A")])
    await wait_for_leader([leader])
    follower = await make_manager([_dynamic_group(calls, "B")])
    await wait_for_leader([leader, follower])

    await create_dynamic_task(
        follower,
        CreateDynamicTaskRequest(task_group_name="g", function_name="work", cron_expression=YEARLY_CRON, name="dyn"),
    )
    await trigger_tasks(follower, task_group_name="g", task_name="dyn")

    ran = await wait_until(lambda: len(calls) >= 1, timeout=4)
    assert ran, "FTM-02: dynamic task created and triggered on a follower never ran"


@known_bug(
    "FTM-02: deleting a dynamic task through a follower leaves it registered on the leader, which keeps scheduling it",
)
async def test_dynamic_task_deleted_on_follower_is_removed_everywhere(make_manager: ManagerFactory) -> None:
    calls: list[str] = []
    leader = await make_manager([_dynamic_group(calls, "A")])
    await wait_for_leader([leader])
    await create_dynamic_task(
        leader,
        CreateDynamicTaskRequest(task_group_name="g", function_name="work", cron_expression=YEARLY_CRON, name="dyn"),
    )
    # The follower starts after the creation, so it loads the task from Redis.
    follower = await make_manager([_dynamic_group(calls, "B")])
    require(any(t.name == "dyn" for t in follower.task_groups[0].tasks), "follower did not load the dynamic task")

    await delete_dynamic_task(follower, task_group_name="g", task_name="dyn")

    def leader_dropped_task() -> bool:
        return all(t.name != "dyn" for t in leader.task_groups[0].tasks)

    dropped = await wait_until(leader_dropped_task, timeout=3)
    assert dropped, "FTM-02: dynamic task deleted on a follower is still registered (and scheduled) on the leader"


# ---------------------------------------------------------------------------
# FTM-03: messages for unknown tasks are acknowledged and lost
# ---------------------------------------------------------------------------


@known_bug(
    "FTM-03: an instance that does not know a task ACKs and deletes its message, "
    "so the run is lost (rolling deploy with mixed versions)",
)
async def test_message_for_unknown_task_survives_until_a_capable_instance_runs_it(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    calls: list[str] = []

    # New version of the application: it adds the task "g/new_task".
    new_group = TaskGroup(name="g")

    @new_group.add_task(YEARLY_CRON, name="new_task")
    async def new_task() -> None:
        calls.append("new")

    name = task_name(new_group, "new_task")
    await seed_next_run_far_future(redis, keys, "g", name)

    # Old version, already running: same group, without the new task. Short
    # heartbeat so that a fix relying on pending-message reclaim (2 s threshold)
    # fits in the test window.
    old = await make_manager([TaskGroup(name="g")], **LONG_TASK_TIMINGS)
    await wait_for_leader([old])

    # The message the new version's leader would publish for its new task
    # (same fields as Coordinator._publish_task), delivered to the old instance.
    message_id = await redis.xadd(
        keys.task_stream_low_key(),
        {"group": "g", "task": name, "scheduled_at": str(time.time())},
    )

    async def delivered() -> bool:
        groups = await redis.xinfo_groups(keys.task_stream_low_key())
        return any(g["last-delivered-id"] == message_id for g in groups)

    require(await wait_until(delivered, timeout=EVENTUALLY), "message was never delivered to the old instance")

    # The new version comes up; the run must eventually happen there.
    await make_manager([new_group], **LONG_TASK_TIMINGS)

    ran = await wait_until(lambda: len(calls) >= 1, timeout=8)
    assert ran, (
        "FTM-03: the message for a task unknown to the consuming instance was acknowledged "
        f"and dropped (stream length now {await redis.xlen(keys.task_stream_low_key())}); "
        "the instance that knows the task never ran it"
    )


# ---------------------------------------------------------------------------
# FTM-04: retry with backoff does not retry
# ---------------------------------------------------------------------------


@known_bug(
    "FTM-04: after a failure only retry_after is written; next_run already points to the "
    "next cron occurrence, so the task is not retried after the backoff",
)
async def test_failed_task_is_retried_after_backoff(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    attempts: list[float] = []
    group = TaskGroup(name="g")

    @group.add_task(YEARLY_CRON, name="flaky")
    async def flaky() -> None:
        attempts.append(time.monotonic())
        if len(attempts) == 1:
            msg = "first attempt fails"
            raise RuntimeError(msg)

    name = task_name(group, "flaky")
    await seed_next_run_far_future(redis, keys, "g", name)
    manager = await make_manager([group], retry_backoff=1.0)
    await wait_for_leader([manager])

    await trigger_tasks(manager, task_group_name="g", task_name=name)
    require(await wait_until(lambda: len(attempts) >= 1, timeout=EVENTUALLY), "task never ran")

    # retry_backoff is 1 s: a retry is expected well within 4 s.
    retried = await wait_until(lambda: len(attempts) >= 2, timeout=4)
    assert retried, "FTM-04: a failed task was not retried after retry_backoff=1s (waits for the next cron run)"


# ---------------------------------------------------------------------------
# FTM-06: the disabled flag expires
# ---------------------------------------------------------------------------


@known_bug("FTM-06: disable sets the flag with ex=statistics_redis_expiration, so it re-enables itself after 5 days")
async def test_disabled_flag_does_not_expire(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    group = TaskGroup(name="g")

    @group.add_task(YEARLY_CRON, name="probe")
    async def probe() -> None:
        return None

    name = task_name(group, "probe")
    await seed_next_run_far_future(redis, keys, "g", name)
    manager = await make_manager([group])

    await disable_tasks(manager, task_group_name="g", task_name=name)

    require(await redis.exists(keys.disabled_key("g", name)), "disable_tasks did not set the flag")
    ttl = await redis.ttl(keys.disabled_key("g", name))
    assert ttl == -1, f"FTM-06: the disabled flag expires on its own (TTL {ttl} s)"


# ---------------------------------------------------------------------------
# FTM-07: every task runs at first startup
# ---------------------------------------------------------------------------


@known_bug(
    "FTM-07: a task without next_run is considered due (by the Coordinator and by the Reconciler), "
    "so it runs at first startup whatever its cron",
)
async def test_yearly_task_does_not_run_at_first_startup(make_manager: ManagerFactory) -> None:
    calls: list[str] = []
    group = TaskGroup(name="g")

    @group.add_task(YEARLY_CRON, name="yearly")
    async def yearly() -> None:
        calls.append("run")

    # Fresh prefix: no next_run stored, as on a first deploy. Reconciliation is
    # on, because the Reconciler also republishes tasks without next_run.
    manager = await make_manager([group], reconciliation_interval=1)
    await wait_for_leader([manager])

    # Covers several Coordinator cycles and Reconciler cycles (1 s).
    ran = await wait_until(lambda: len(calls) >= 1, timeout=BUG_WINDOW)
    assert not ran, f"FTM-07: a task with cron {YEARLY_CRON!r} ran right at first startup"


# ---------------------------------------------------------------------------
# FTM-11 / FTM-12: tag handling
# ---------------------------------------------------------------------------


@known_bug("FTM-11: the tag filter of the bulk API endpoints also matches tasks without tags")
async def test_tag_filter_does_not_match_untagged_tasks(
    make_manager: ManagerFactory,
    redis: Redis,
    keys: RedisKeyBuilder,
) -> None:
    group = TaskGroup(name="g")

    @group.add_task(YEARLY_CRON, name="untagged")
    async def untagged() -> None:
        return None

    name = task_name(group, "untagged")
    await seed_next_run_far_future(redis, keys, "g", name)
    manager = await make_manager([group])

    # No task carries this tag: the endpoint must answer 404 and touch nothing.
    matched: list[str] = []
    try:
        result = await disable_tasks(manager, tag="does-not-exist")
        matched = [a.task for a in result.affected_tasks]
    except HTTPException as exc:
        require(exc.status_code == 404, f"unexpected HTTP status {exc.status_code}")
    assert matched == [], f"FTM-11: disable with tag='does-not-exist' matched untagged tasks: {matched}"
    assert not await redis.exists(keys.disabled_key("g", name))


@known_bug("FTM-12: operator precedence in TaskGroup.add_task drops the task tags when the group has tags")
async def test_task_keeps_its_tags_when_the_group_has_tags(make_manager: ManagerFactory) -> None:
    group = TaskGroup(name="g", tags=["group"])

    @group.add_task(YEARLY_CRON, name="tagged", tags=["task-tag"])
    async def tagged() -> None:
        return None

    manager = await make_manager([group])

    tasks = await get_tasks(manager, tag="task-tag")
    assert [t.tags for t in tasks] == [["group", "task-tag"]], (
        f"FTM-12: filtering by the task's own tag found {[t.tags for t in tasks]}"
    )
