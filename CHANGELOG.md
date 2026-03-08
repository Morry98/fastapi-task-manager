# Release Notes

## Latest Changes

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

* 📝 Add first implementation of docs available at [https://fastapi-task-manager.morando.uk](https://fastapi-task-manager.morando.uk)

### Internals

* 🔒 Add bandit pre-commit hook for security linting.
* ✅ Add `pytest-asyncio` with async test coverage for dynamic tasks, statistics, config, schemas, and more.
* ♻️ Extract `interruptible_sleep` into a shared `async_utils` module.
* ♻️ Fix race condition in distributed lock by using `SET NX` instead of `EXISTS + SET` pattern.
* ♻️ Move pre-commit checks from mypy+vermin to [ty from astral](https://docs.astral.sh/ty/)
* ⬆️ Pre-commit bump uv-pre-commit from 0.9.7 to 0.9.18.
* ⬆️ Pre-commit bump ruff-pre-commit from 0.14.3 to 0.14.10.
* ⬆️ Bump dependencies in uv.lock file, for dev purposes:
*    - annotated-doc added 0.0.4
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
