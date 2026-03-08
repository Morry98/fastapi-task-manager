# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI Task Manager is a Python library (v0.8.0) that provides scheduled task management for FastAPI applications using Redis for distributed locking and task state. It enables cron-based task scheduling with single-instance execution safety across multiple app instances.

- **Package**: `fastapi-task-manager` on PyPI (also published to TestPyPI)
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

This project uses **pre-commit** to enforce code quality on every commit. The configuration is in `.pre-commit-config.yaml`.

### Hooks (run automatically on `git commit`)

1. **pre-commit-hooks** (v6.0.0): `check-added-large-files`, `check-merge-conflict`, `end-of-file-fixer`, `check-toml`, `check-yaml`, `mixed-line-ending`, `trailing-whitespace`
2. **remove-tabs** (Lucas-C, v1.5.6)
3. **uv-lock** (astral-sh): ensures `uv.lock` stays in sync
4. **ruff-check** + **ruff-format** (astral-sh): lint with `--fix --unsafe-fixes` and format
5. **bandit** (v1.9.4): security linter
6. **ty check** (local hook): type checking with Astral's ty

### Exclusions

Pre-commit excludes test files (`.*test.*\.py`, `.*/test/.*`) and markdown (`*.md`) from most hooks.

### Manual-stage hooks

- **prune-stale-tags**: `git fetch origin --prune --prune-tags --tags` (run with `pre-commit run --hook-stage manual prune-stale-tags`)

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

- **Statistics** (`statistics.py`): Tracks task execution history (runs, durations).

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
- `_runs`: History of execution timestamps
- `_durations_second`: History of execution durations
- `_running`: Heartbeat key indicating task is currently executing

### Public API

The library exports from `__init__.py`:
- `TaskManager`
- `TaskGroup`
- `Config`
- `HealthResponse`

## Testing

- Framework: **pytest** with **pytest-asyncio** (asyncio_mode = "auto")
- Coverage: **coverage** package
- Tests use `pytest-asyncio` for async test support

## Documentation

- Built with **MkDocs** + **Material for MkDocs**
- Plugins: awesome-pages, glightbox, macros, termynal
- Serve locally: `uv run mkdocs serve`

## Code Style

- Line length: 120 characters
- Uses Ruff for linting with extensive rule sets (see `pyproject.toml`)
- Type checking with `ty` (Astral's type checker)
- McCabe complexity limit: 12
- Max function arguments: 8
- Pre-commit excludes test files and markdown from some checks
- **Code must always be commented**: Add clear and concise comments to explain non-obvious logic
- **Language requirement**: All code (including comments) and documentation must be written in English
