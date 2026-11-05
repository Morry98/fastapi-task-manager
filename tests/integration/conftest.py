"""Fixtures for the integration suite, which runs against a real Redis server.

The Redis server is selected with the ``REDIS_URL`` environment variable
(default ``redis://localhost:6379/15``). When the server does not answer, every
integration test is skipped instead of failing, so the suite stays usable on
machines without Redis.

Isolation rules:
- every test gets its own random ``redis_key_prefix``, so tests never see each
  other's keys and can share a Redis database with other users;
- at teardown only the keys under that prefix are deleted (``SCAN`` + ``DEL``),
  the database is never flushed.
"""

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse

import pytest
from fastapi import FastAPI
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from fastapi_task_manager import Config, TaskGroup, TaskManager
from fastapi_task_manager.redis_keys import RedisKeyBuilder

DEFAULT_REDIS_URL = "redis://localhost:6379/15"

# Timings scaled down from the defaults so that every scenario completes in a
# few seconds. Leader lock TTL = ceil(0.5 * 3) = 2 s; running key TTL =
# ceil(0.5 * 3) = 2 s; stuck-message threshold = ceil(0.5 * 9) = 5 s.
# The Reconciler is kept out of the test window by default: a trigger stores
# next_run = 0, which the Reconciler can see as overdue and republish while the
# Coordinator is publishing the same run, so it would run twice (a race in the
# library, not in the tests). Scenarios about reconciliation enable it explicitly.
FAST_CONFIG: dict[str, Any] = {
    "poll_interval": 0.05,
    "stream_block_ms": 100,
    "leader_heartbeat_interval": 0.5,
    "leader_retry_interval": 0.2,
    "reconciliation_interval": 3600,
    "running_heartbeat_interval": 0.5,
    "retry_backoff": 1.0,
    "retry_backoff_max": 1.0,
}

# A cron expression that never fires during a test run (midnight, January 1st).
# Used together with a pre-seeded next_run so that tasks run only when a test
# triggers them explicitly.
YEARLY_CRON = "0 0 1 1 *"


@dataclass(frozen=True)
class RedisTarget:
    """Connection parameters parsed from ``REDIS_URL``."""

    url: str
    host: str
    port: int
    password: str | None
    db: int


def _parse_redis_url(url: str) -> RedisTarget:
    """Split a ``redis://[:password@]host[:port][/db]`` URL into Config fields."""
    parsed = urlparse(url)
    db_path = parsed.path.lstrip("/")
    return RedisTarget(
        url=url,
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=unquote(parsed.password) if parsed.password else None,
        db=int(db_path) if db_path else 0,
    )


@pytest.fixture(scope="session")
def redis_target() -> RedisTarget:
    """Return the Redis server to test against, or skip when it does not answer."""
    target = _parse_redis_url(os.environ.get("REDIS_URL", DEFAULT_REDIS_URL))
    client = SyncRedis(
        host=target.host,
        port=target.port,
        password=target.password,
        db=target.db,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
    except Exception as exc:  # any connection problem means "no Redis available"
        message = f"Redis not reachable at {target.url}: {exc!r}"
        # In CI Redis is a provided service: a missing server must fail the run,
        # not turn the whole suite into silent skips.
        if os.environ.get("REDIS_REQUIRED"):
            pytest.fail(message)
        pytest.skip(message)
    finally:
        client.close()
    return target


@pytest.fixture
def key_prefix() -> str:
    """Return a Redis key prefix unique to the current test."""
    return f"ftm-it-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def keys(key_prefix: str) -> RedisKeyBuilder:
    """Return a key builder bound to the test prefix."""
    return RedisKeyBuilder(key_prefix)


@pytest.fixture
async def redis(redis_target: RedisTarget, key_prefix: str) -> AsyncIterator[Redis]:
    """Return an async Redis client for assertions; delete the test's keys afterwards."""
    client = Redis(
        host=redis_target.host,
        port=redis_target.port,
        password=redis_target.password,
        db=redis_target.db,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        # Only the keys owned by this test are removed: never FLUSHDB/FLUSHALL.
        stale_keys = [key async for key in client.scan_iter(match=f"{key_prefix}*", count=500)]
        if stale_keys:
            await client.delete(*stale_keys)
        await client.aclose()


@pytest.fixture
def release() -> asyncio.Event:
    """Event that long-running probe tasks wait on; set at teardown to let them finish."""
    return asyncio.Event()


ManagerFactory = Callable[..., Awaitable[TaskManager]]


@pytest.fixture
async def make_manager(
    redis_target: RedisTarget,
    key_prefix: str,
    redis: Redis,  # noqa: ARG001 - requested so that key cleanup runs after the managers stop
    release: asyncio.Event,
) -> AsyncIterator[ManagerFactory]:
    """Factory that builds (and by default starts) TaskManager instances.

    Every instance shares the test prefix and Redis database, which is how
    several application replicas see each other in production. All instances
    are stopped at teardown.
    """
    created: list[TaskManager] = []

    async def factory(groups: list[TaskGroup], *, start: bool = True, **overrides: Any) -> TaskManager:
        config = Config(
            redis_host=redis_target.host,
            redis_port=redis_target.port,
            redis_password=redis_target.password,
            redis_db=redis_target.db,
            redis_key_prefix=key_prefix,
            **{**FAST_CONFIG, **overrides},
        )
        manager = TaskManager(app=FastAPI(), config=config)
        for group in groups:
            manager.add_task_group(group)
        created.append(manager)
        if start:
            await manager.start()
        return manager

    yield factory

    # Let any probe still blocked on the event finish, otherwise stop() would
    # wait for it (the consumer waits for running tasks without a timeout).
    release.set()
    # Stop every instance even if one of them fails to stop, then report the first error.
    errors: list[BaseException] = []
    for manager in reversed(created):
        if manager.runner is not None:
            try:
                await manager.stop()
            except Exception as exc:
                errors.append(exc)
    if errors:
        raise errors[0]


# ---------------------------------------------------------------------------
# Helpers shared by the scenario modules
# ---------------------------------------------------------------------------


async def wait_until(predicate: Callable[[], Any], timeout: float, interval: float = 0.05) -> bool:
    """Poll ``predicate`` (sync or async) until it is truthy or ``timeout`` elapses.

    Returns True as soon as the condition holds, False on timeout. Used both
    to wait for an expected event and, with a bounded timeout, to give an
    unwanted event the chance to happen.
    """
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(interval)


class PreconditionError(Exception):
    """A scenario could not reach the state it needs before its real assertion.

    Deliberately not an AssertionError: the known-bug tests are
    ``xfail(raises=AssertionError)``, and a broken setup must surface as a real
    failure instead of being mistaken for the documented bug.
    """


def require(condition: object, message: str) -> None:
    """Raise PreconditionError with ``message`` when ``condition`` is falsy."""
    if not condition:
        raise PreconditionError(message)


async def wait_for_leader(managers: list[TaskManager], timeout: float = 5.0) -> TaskManager:
    """Wait until exactly one of ``managers`` is leader and return it."""

    def single_leader() -> bool:
        return sum(1 for m in managers if m.runner is not None and m.runner.is_leader) == 1

    require(await wait_until(single_leader, timeout), "no single leader was elected in time")
    return next(m for m in managers if m.runner is not None and m.runner.is_leader)


async def seed_next_run_far_future(redis: Redis, keys: RedisKeyBuilder, group: str, task: str) -> None:
    """Store a next_run one year ahead, so the task only runs when a test triggers it.

    Without this, a task without next_run is scheduled immediately at startup
    (see FTM-07), which would make run counts depend on that behaviour.
    """
    one_year_ahead = datetime.now(timezone.utc).timestamp() + 365 * 24 * 3600
    await redis.set(keys.next_run_key(group, task), one_year_ahead)


def task_name(group: TaskGroup, prefix: str) -> str:
    """Return the internal name of the only task in ``group`` whose name starts with ``prefix``."""
    matches = [t.name for t in group.tasks if t.name.startswith(prefix)]
    require(len(matches) == 1, f"expected one task named {prefix}*, found {matches}")
    return matches[0]
