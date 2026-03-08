# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI Task Manager is a Python library that provides scheduled task management for FastAPI applications using Redis for distributed locking and task state. It enables cron-based task scheduling with single-instance execution safety across multiple app instances.

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

## Architecture

### Core Components

The library follows a hierarchical structure: **TaskManager** → **TaskGroup** → **Task**

- **TaskManager** (`task_manager.py`): Entry point that integrates with FastAPI's lifespan. Creates Redis connection and spawns the Runner. Provides API router via `get_manager_router()`.

- **TaskGroup** (`task_group.py`): Organizes related tasks. Tasks are registered via the `@task_group.add_task(cron_expr)` decorator. Supports multiple cron expressions and kwargs per task function.

- **Runner** (`runner.py`): Orchestrates stream mode components (LeaderElector, Coordinator, StreamConsumer, Reconciler). Uses Redis Streams with leader election for task scheduling and consumer groups for execution.

- **Config** (`config.py`): Pydantic model for configuration. Key settings:
  - `redis_key_prefix`: Namespace for Redis keys
  - `concurrent_tasks`: Max parallel tasks (default: 2)
  - `statistics_history_runs`: Number of runs to track (default: 30)

### Redis Key Patterns

All keys are prefixed with `{redis_key_prefix}_{task_group_name}_{task_name}_`:
- `_next_run`: Timestamp of next scheduled execution
- `_disabled`: Flag to pause task execution
- `_runs`: History of execution timestamps
- `_durations_second`: History of execution durations
- `_running`: Heartbeat key indicating task is currently executing

### Public API

The library exports three classes from `__init__.py`:
- `TaskManager`
- `TaskGroup`
- `Config`

## Code Style

- Line length: 120 characters
- Uses Ruff for linting with extensive rule sets (see `pyproject.toml`)
- Type checking with `ty` (Astral's type checker)
- McCabe complexity limit: 12
- Max function arguments: 8
- Pre-commit excludes test files and markdown from some checks
- **Code must always be commented**: Add clear and concise comments to explain non-obvious logic
- **Language requirement**: All code (including comments) and documentation must be written in English
