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

- **Runner** (`runner.py`): Async loop that polls tasks and executes them. Uses Redis keys for distributed locking (`{prefix}_{group}_{task}_runner_uuid`) to ensure only one instance runs a task. Uses `ForceAcquireSemaphore` for concurrency control.

- **Config** (`config.py`): Pydantic model for configuration. Key settings:
  - `redis_key_prefix`: Namespace for Redis keys
  - `concurrent_tasks`: Max parallel tasks (default: 2)
  - `statistics_history_runs`: Number of runs to track (default: 30)

### Redis Key Patterns

All keys are prefixed with `{redis_key_prefix}_{task_group_name}_{task_name}_`:
- `_next_run`: Timestamp of next scheduled execution
- `_runner_uuid`: Lock for single-instance execution
- `_disabled`: Flag to pause task execution
- `_runs`: History of execution timestamps
- `_durations_second`: History of execution durations

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

## Feature Request Workflow

**IMPORTANT**: Before implementing any feature or change request, follow this mandatory workflow:

### 1. Create a Feature Document

For every request, create a markdown file in the `features_docs/` folder:

- **Filename format**: `yyyymmdd_hhmm__feature_name.md` (use current system date and time)
- **Example**: `20251224_1430__add_task_retry_mechanism.md`

### 2. Document Content

The feature document must include:

- **Request Summary**: Brief description of what was requested
- **Findings**: Analysis of the current codebase, relevant files, existing patterns
- **Thoughts & Considerations**: Trade-offs, potential issues, architectural decisions
- **Implementation Plan**: Step-by-step list of changes to be made
- **Files to Modify/Create**: List of affected files
- **Questions/Clarifications**: Any open questions or assumptions

### 3. Request Approval

**ALWAYS ask for user consent before proceeding with implementation.** Do not start coding until explicit approval is given.

### Purpose

This workflow serves two critical purposes:

1. **Review & Validation**: Allows the user to verify and evaluate every feature before implementation begins
2. **Knowledge Tracking**: Maintains a history of decisions, rationale, and progress for future reference
