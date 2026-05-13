# Release Notes

## Latest

### Bug fixes

* 🐛 **Consumer group loss after `FLUSHALL`**: `FLUSHALL` at runtime deletes all stream consumer groups. The Coordinator recreates streams via `XADD`, but `xreadgroup` kept throwing `NOGROUP` on every iteration. Catch `NOGROUP` in `_try_read_stream` and call `setup_consumer_groups()` to recover; the Reconciler republishes any tasks queued before the group was restored.

* 🐛 **False "Task failed" after flush**: When a task finishes while the consumer group is gone, `xack` throws `NOGROUP`. The generic handler in `_execute_and_ack` was catching this, logging "Task failed", and applying backoff on a task that actually succeeded. Catch `NOGROUP` in `_ack_message` and log a warning instead — the message is already gone from the PEL.

## 1.1.0 - 2026-04-15

### Features

* 🚀 **Parallel execution control (`allow_parallel`)**:  
     Add configurable `allow_parallel` setting to control whether the same task can run multiple times concurrently.  
     When set to `False`, the coordinator skips scheduling if the task is already running on any worker (checked via 
  Redis heartbeat key).  
     Supports three-level cascade resolution: **task > task group > global config**, the most specific non-null 
  value wins.  
     Available on `Config` (global default), `TaskGroup` (group-level override), `@task_group.add_task()` decorator, `task_group.add_dynamic_task()`, and the `POST /tasks` REST API. Dynamic task definitions include the setting in Redis persistence for restart survival.

### Internals
* ⬆️ Bump dependencies in uv.lock file, for dev purposes:
     - anyio from 4.12.1 to 4.13.0
     - charset-normalizer from 3.4.5 to 3.4.7
     - coverage from 7.13.4 to 7.13.5
     - fastapi from 0.135.1 to 0.135.3
     - mkdocs-get-deps from 0.2.0 to 0.2.2
     - mkdocs-material from 9.7.4 to 9.7.6
     - platformdirs from 4.9.4 to 4.9.6
     - pydantic from 2.12.5 to 2.13.0
     - pydantic-core from 2.41.5 to 2.46.0
     - pygments from 2.19.2 to 2.20.0
     - pymdown-extensions from 10.21 to 10.21.2
     - pytest from 9.0.2 to 9.0.3
     - redis from 7.3.0 to 7.4.0
     - requests from 2.32.5 to 2.33.1
     - ruff from 0.15.5 to 0.15.10
     - setuptools from 82.0.0 to 82.0.1
     - starlette from 0.52.1 to 1.0.0
     - termynal from 0.13.1 to 0.14.0
     - ty from 0.0.21 to 0.0.29

## 1.0.0 - 2026-03-09

### Features

* 🚀 **Redis Streams execution engine**: Replace polling-based task execution with Redis Streams and leader election as the sole execution strategy. Includes `LeaderElector` for distributed leader election via Redis `SET NX`, `Coordinator` for evaluating cron expressions and publishing tasks to streams, and `StreamConsumer` for consuming and executing tasks from dual-priority streams.
* 🚀 **Exponential backoff retry**: Add configurable retry with exponential backoff for failed tasks. On success the backoff state resets automatically. Includes per-task override support and a `/reset-retry` API endpoint.
* 🚀️ **Reconciler and task heartbeat**: Leader-only reconciliation loop that detects missed or stuck tasks and republishes them to the Redis stream. Tasks maintain a heartbeat via a running key to distinguish between actively-running and stalled executions.
* 🚀 **Statistics storage with Redis Streams**: Migrate statistics from Redis Lists to a single Redis Stream per task. Each entry contains both `ts` and `dur` fields, ensuring data correlation. Uses `XADD` with approximate `MAXLEN` for bounded storage.
* 🚀 **Dynamic task CRUD API**: Runtime task management allowing tasks to be created and deleted via the management API. Functions are registered in a `TaskGroup` registry and definitions are persisted in a Redis Hash to survive restarts.
* 🚀 **Worker identity**: Introduce `WorkerIdentity` for traceable worker identification with hostname, PID, and short UUID. Add `RedisKeyBuilder` to centralize all Redis key construction.

### Reworks

* ♻️ **Revamp management API**: Rewrite task router services to use the shared async Redis client. Convert 
  single-task actions to bulk operations. 
  Add new endpoints: `GET /health`, `GET /config`, `POST /tasks/trigger`, `DELETE /tasks/statistics`.
* ♻️ Switch all modules to per-component loggers.
* ♻️ Rename config `app_name` to `redis_key_prefix` to better reflect its purpose.

### Docs

* 📝 Add first implementation of docs available at [https://fastapi-task-manager.morry98.com](https://fastapi-task-manager.morry98.com)

### Internals

* 🔒 Add bandit pre-commit hook for security linting.
* ✅ Add `pytest-asyncio` with async test coverage for dynamic tasks, statistics, config, schemas, and more.
* ♻️ Extract `interruptible_sleep` into a shared `async_utils` module.
* ♻️ Fix race condition in distributed lock by using `SET NX` instead of `EXISTS + SET` pattern.
* ♻️ Move pre-commit checks from mypy+vermin to [ty from astral](https://docs.astral.sh/ty/)
* ⬆️ Pre-commit bump uv-pre-commit from 0.9.7 to 0.9.18.
* ⬆️ Pre-commit bump ruff-pre-commit from 0.14.3 to 0.14.10.
* ⬆️ Bump dependencies in uv.lock file, for dev purposes:
     - annotated-doc added 0.0.4
     - anyio from 4.11.0 to 4.12.1
     - backrefs from 6.1 to 6.2
     - certifi from 2026.1.4 to 2026.2.25
     - charset-normalizer from 3.4.4 to 3.4.5
     - coverage from 7.11.1 to 7.13.0
     - exceptiongroup from 1.3.0 to 1.3.1
     - fastapi from 0.121.0 to 0.135.1
     - idna from 3.10 to 3.11
     - markdown-include-variants from 0.0.5 to 0.0.8
     - mkdocs-macros-plugin from 1.4.1 to 1.5.0
     - mkdocs-material from 9.6.23 to 9.7.4
     - platformdirs from 4.5.0 to 4.9.4
     - pydantic from 2.12.4 to 2.12.5
     - pydantic-core from 2.33.2 to 2.41.5
     - pydantic-settings from 2.12.0 to 2.13.1
     - pymdown-extensions from 10.16.1 to 10.21
     - pytest from 9.0.1 to 9.0.2
     - python-dotenv from 1.2.1 to 1.2.2
     - redis from 7.0.1 to 7.3.0
     - ruff from 0.15.0 to 0.15.5
     - selectolax from 0.4.3 to 0.4.7
     - sniffio removed
     - starlette from 0.49.3 to 0.52.1
     - ty from 0.0.16 to 0.0.21
     - typing-inspection from 0.4.1 to 0.4.2
     - urllib3 from 2.5.0 to 2.6.2

## 0.8.0 - 2026-02-12

### Internals

* ♻️ Change pypi package 'cronexpr'  with 'cronsim' due to maintenance issues.
     No side effects in package usage.

## 0.7.0 - 2025-xx-xx

TBC
