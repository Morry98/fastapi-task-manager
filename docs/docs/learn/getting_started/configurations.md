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
{* ./docs_src/tutorial/configurations_py310.py ln[10] *}

The hostname or IP address of the Redis server. This is the only **required** configuration parameter with no default value.

### Redis Port
{* ./docs_src/tutorial/configurations_py310.py ln[11] *}

The port number of the Redis server.
Default value is `6379`.

### Redis Password
{* ./docs_src/tutorial/configurations_py310.py ln[12] *}

The password for authenticating with the Redis server. Set to `None` if your Redis instance does not require authentication.
Default value is `None`.

### Redis DB
{* ./docs_src/tutorial/configurations_py310.py ln[13] *}

The Redis database number to use. Redis supports multiple databases (0-15 by default).
Default value is `0`.

---

## Runner Configuration

These settings control the core task scheduling loop.

### Poll Interval
{* ./docs_src/tutorial/configurations_py310.py ln[15] *}

The interval (in seconds) between coordinator scheduling cycles. Lower values mean tasks are picked up faster but increase Redis load.
Default value is `0.1`.

### Worker Service Name
{* ./docs_src/tutorial/configurations_py310.py ln[16] *}

The service name used for worker identification. This appears in health check responses and logs to help identify which service a worker belongs to.
Default value is `"fastapi-task-manager"`.

---

## Streams Configuration

These settings control the Redis Streams-based task distribution system.

### Stream Max Length
{* ./docs_src/tutorial/configurations_py310.py ln[18] *}

The maximum number of entries retained in the task stream. Uses approximate trimming (`MAXLEN ~`) to keep the stream size bounded. Older entries are automatically removed.
Default value is `10000`.

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

## Running Heartbeat Configuration

While a task is executing, the worker periodically renews a heartbeat key in Redis. If a worker crashes, the key expires, signaling that the task is no longer being executed.

### Running Heartbeat Interval
{* ./docs_src/tutorial/configurations_py310.py ln[30] *}

The interval (in seconds) between heartbeat renewals while a task is executing. The worker renews the running key at this interval.
Default value is `3.0`.
