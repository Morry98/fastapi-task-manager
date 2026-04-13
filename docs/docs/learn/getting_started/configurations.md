# Configurations

This is the entire code example for the configurations tutorial.

We will see each config in detail with his own section in the next parts of this tutorial.

{* ./docs_src/tutorial/configurations_py310.py *}

## App Configuration

### Redis Key Prefix
{* ./docs_src/tutorial/configurations_py310.py ln[5] *}

This configuration is used as custom prefix for all the keys used by the package in redis. Pay attention to make it unique if you are using the same redis instance for multiple applications on the same redis db.
Default value is `__name__`.

### Concurrent Tasks
{* ./docs_src/tutorial/configurations_py310.py ln[6] *}

This configuration is used to set the maximum number of concurrent tasks that can be executed by each worker.
Default value is `2`.

### Statistics Redis Expiration
{* ./docs_src/tutorial/configurations_py310.py ln[7] *}

This configuration sets the TTL (in seconds) for statistics-related keys in Redis. After this time, the statistics data will expire and be automatically removed by Redis.
Default value is `432000` (5 days).

### Statistics History Runs
{* ./docs_src/tutorial/configurations_py310.py ln[8] *}

This configuration sets how many historical execution entries are kept per task in the statistics Redis Stream. Each entry contains both the run timestamp and duration. Older entries are automatically trimmed via `XADD MAXLEN`.
Default value is `500`.

---

## Redis Configuration

### Redis Host
{* ./docs_src/tutorial/configurations_py310.py ln[11] *}

The hostname or IP address of the Redis server. This is the only **required** configuration parameter with no default value.

### Redis Port
{* ./docs_src/tutorial/configurations_py310.py ln[12] *}

The port number of the Redis server.
Default value is `6379`.

### Redis Password
{* ./docs_src/tutorial/configurations_py310.py ln[13] *}

The password for authenticating with the Redis server. Set to `None` if your Redis instance does not require authentication.
Default value is `None`.

### Redis DB
{* ./docs_src/tutorial/configurations_py310.py ln[14] *}

The Redis database number to use. Redis supports multiple databases (0-15 by default).
Default value is `0`.

---

## Runner Configuration

These settings control the core task scheduling loop.

### Poll Interval
{* ./docs_src/tutorial/configurations_py310.py ln[16] *}

The interval (in seconds) between coordinator scheduling cycles. Lower values mean tasks are picked up faster but increase Redis load.
Default value is `0.1`.

### Worker Service Name
{* ./docs_src/tutorial/configurations_py310.py ln[17] *}

The service name used for worker identification. This appears in health check responses and logs to help identify which service a worker belongs to.
Default value is `"fastapi-task-manager"`.

---

## Streams Configuration

These settings control the Redis Streams-based task distribution system.

### Stream Block Timeout
{* ./docs_src/tutorial/configurations_py310.py ln[19] *}

The block timeout (in milliseconds) for `XREADGROUP` when consumers wait for new messages. Higher values reduce Redis round-trips but increase shutdown latency.
Default value is `1000`.

---

## Leader Election Configuration

FastAPI Task Manager uses distributed leader election via Redis to ensure that only one instance schedules tasks at a time, while all instances can execute them.

### Leader Heartbeat Interval
{* ./docs_src/tutorial/configurations_py310.py ln[21] *}

The interval (in seconds) between leader lock renewals. The leader periodically renews its lock to signal it is still alive.
Default value is `3.0`.

### Leader Retry Interval
{* ./docs_src/tutorial/configurations_py310.py ln[22] *}

The interval (in seconds) between leadership acquisition attempts for follower instances. When a worker is not the leader, it tries to acquire leadership at this interval.
Default value is `5.0`.

---

## Reconciliation Configuration

The reconciler detects and recovers stale or failed tasks. It runs only on the leader instance.

### Reconciliation Interval
{* ./docs_src/tutorial/configurations_py310.py ln[24] *}

The interval (in seconds) between reconciliation checks. The reconciler scans for overdue or stuck tasks at this interval.
Default value is `30`.

---

## Retry / Backoff Configuration

When a task fails, FastAPI Task Manager applies exponential backoff to delay re-execution. This prevents rapid failure loops and gives external dependencies time to recover.

### Retry Backoff
{* ./docs_src/tutorial/configurations_py310.py ln[26] *}

The initial backoff delay (in seconds) after a task failure. The first retry will be delayed by this amount.
Default value is `1.0`.

//// tip | Per-task override
This setting can be overridden on individual tasks via the `retry_backoff` parameter on `@task_group.add_task()`.
////

### Retry Backoff Max
{* ./docs_src/tutorial/configurations_py310.py ln[27] *}

The maximum backoff delay (in seconds). The delay will never exceed this value, regardless of how many consecutive failures occur.
Default value is `60.0`.

//// tip | Per-task override
This setting can be overridden on individual tasks via the `retry_backoff_max` parameter on `@task_group.add_task()`.
////

### Retry Backoff Multiplier
{* ./docs_src/tutorial/configurations_py310.py ln[28] *}

The multiplier applied to the current delay after each consecutive failure. For example, with default settings: 1s, 2s, 4s, 8s, 16s, 32s, 60s (capped).
Default value is `2.0`.

---

## Parallel Execution Control

The `allow_parallel` setting controls whether the same task can run multiple times concurrently. When set to `False`, the coordinator will **skip scheduling** the task if it is already running on any worker. This is useful for long-running tasks where overlapping executions would be problematic.

This setting can be configured at **three levels**, with a cascade resolution order: **task > task group > global config**.

- If a task sets `allow_parallel`, that value is used.
- Otherwise, if the task group sets `allow_parallel`, that value is used.
- Otherwise, the global `Config.allow_parallel` value is used (default: `True`).

### Global (Config)

{* ./docs_src/tutorial/configurations_py310.py ln[9] *}

Sets the default for all tasks across the entire application. Default value is `True`.

### Task Group

```python
# All tasks in this group default to no parallel execution
my_tasks = TaskGroup(name="My Tasks", allow_parallel=False)
```

Sets the default for all tasks within the group. Set to `None` (the default) to inherit from the global config.

### Task

```python
# This specific task cannot run in parallel, even if the group allows it
@my_tasks.add_task(
    "*/5 * * * *",
    name="slow_sync",
    allow_parallel=False,
)
async def slow_sync():
    await asyncio.sleep(7)
```

Overrides both the group and global setting for this specific task. Set to `None` (the default) to inherit from the task group.

//// tip | Cascade example
With `Config(allow_parallel=True)` and `TaskGroup(allow_parallel=False)`:

- A task with `allow_parallel=True` **will** allow parallel runs (task wins)
- A task with `allow_parallel=None` **will not** allow parallel runs (inherits from group)
////

//// note | Multi-worker safe
This check uses the Redis `running` heartbeat key, which is shared across all workers. Even if the task is running on a different instance, the coordinator will correctly skip scheduling it.
////

---

## Running Heartbeat Configuration

While a task is executing, the worker periodically renews a heartbeat key in Redis. If a worker crashes, the key expires, signaling that the task is no longer being executed.

### Running Heartbeat Interval
{* ./docs_src/tutorial/configurations_py310.py ln[30] *}

The interval (in seconds) between heartbeat renewals while a task is executing. The worker renews the running key at this interval.
Default value is `3.0`.
