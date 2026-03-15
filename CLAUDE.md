# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI Task Manager is a Python library that provides scheduled task management for FastAPI applications using Redis for distributed locking and task state. It enables cron-based task scheduling with single-instance execution safety across multiple app instances.

- **Package**: `fastapi-task-manager` on PyPI
- **Python**: >=3.10 (supports 3.10–3.14)
- **License**: MIT
- **Build system**: `uv_build`
- **Dependencies**: `cronsim`, `fastapi`, `pydantic`, `redis`

## Development Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run tests with coverage
uv run coverage run -m pytest && uv run coverage report

# Type checking (uses Astral's ty, not mypy)
uv run ty check .

# Lint and format
uv run ruff check --fix --unsafe-fixes .
uv run ruff format .

# Run all pre-commit checks
pre-commit run --all-files

# Serve documentation locally
uv run mkdocs serve

# Build package
uv build
```

## Pre-commit

This project uses **pre-commit** to enforce code quality on every commit. Hooks include formatting (Ruff), security (Bandit), type checking (ty), and more. See `.pre-commit-config.yaml` for the full configuration.

- Run manually: `pre-commit run --all-files`
- Prune stale tags: `pre-commit run --hook-stage manual prune-stale-tags`

## Architecture

### Core Components

The library follows a hierarchical structure: **TaskManager** → **TaskGroup** → **Task**

Source code lives in `src/fastapi_task_manager/`.

- **TaskManager** (`task_manager.py`): Entry point that integrates with FastAPI's lifespan. Creates Redis connection and spawns the Runner. Provides API router via `get_manager_router()`.

- **TaskGroup** (`task_group.py`): Organizes related tasks. Tasks are registered via the `@task_group.add_task(cron_expr)` decorator. Supports multiple cron expressions and kwargs per task function.

- **Runner** (`runner.py`): Orchestrates stream mode components (LeaderElector, Coordinator, StreamConsumer, Reconciler). Uses Redis Streams with leader election for task scheduling and consumer groups for execution.

- **LeaderElection** (`leader_election.py`): Distributed leader election via Redis to ensure only one instance schedules tasks.

- **Coordinator** (`coordinator.py`): Determines which tasks are due and publishes them to the Redis stream.

- **StreamConsumer** (`stream_consumer.py`): Consumes task messages from Redis Streams using consumer groups for distributed execution.

- **Reconciler** (`reconciler.py`): Detects and recovers stale/failed tasks to ensure consistency.

- **Statistics** (`statistics.py`): Tracks task execution history using Redis Streams (timestamp + duration per entry).

- **Config** (`config.py`): Pydantic model for configuration. Key settings:
  - `redis_key_prefix`: Namespace for Redis keys
  - `concurrent_tasks`: Max parallel tasks (default: 2)
  - `statistics_history_runs`: Number of runs to track (default: 30)

- **Schemas** (`schema/`): Pydantic response models — `HealthResponse`, `TaskGroup`, `Task`, `WorkerIdentity`.

- **Redis Keys** (`redis_keys.py`): Centralized definition of Redis key patterns.

- **Task Router Services** (`task_router_services.py`): Service layer for the management API endpoints.

- **Async Utils** (`async_utils.py`): Shared async helper utilities.

### Redis Key Patterns

All keys are prefixed with `{redis_key_prefix}_{task_group_name}_{task_name}_`:
- `_next_run`: Timestamp of next scheduled execution
- `_disabled`: Flag to pause task execution
- `_stats_stream`: Redis Stream with execution history (each entry has `ts` and `dur` fields)
- `_running`: Heartbeat key indicating task is currently executing

### Public API

The library exports from `__init__.py`:
- `TaskManager`
- `TaskGroup`
- `Config`
- `HealthResponse`

## Testing & Documentation

- Tests: **pytest** with **pytest-asyncio** (asyncio_mode = "auto"), coverage via **coverage** package
- Docs: **MkDocs** + **Material for MkDocs** — serve locally with `uv run mkdocs serve`

## Code Style

- Line length: 120 characters
- Uses Ruff for linting with extensive rule sets (see `pyproject.toml`)
- Type checking with `ty` (Astral's type checker)
- McCabe complexity limit: 12
- Max function arguments: 8
- **Code must always be commented**: Add clear and concise comments to explain non-obvious logic
- **Language requirement**: All code (including comments) and documentation must be written in English
