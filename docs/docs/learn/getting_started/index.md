# Getting Started

Welcome to the FastAPI Task Manager Getting Started Guide! This guide will walk you through the setup process step by step.

---

## What you will learn

1. [**Installation**](installation.md) - Install the package in your FastAPI project
2. [**Configurations**](configurations.md) - Understand and customize all configuration options
3. [**API Reference**](../api-reference.md) - Explore the built-in management API endpoints
4. [**Architecture**](../architecture.md) - Understand how the system works under the hood

---

## Prerequisites

Before you begin, make sure you have:

- A **FastAPI** project set up ([FastAPI installation guide](https://fastapi.tiangolo.com/#installation){ .external-link target="_blank" })
- A running **Redis** server ([Redis installation guide](https://redis.io/docs/latest/operate/rs/installing-upgrading/){ .external-link target="_blank" })
- **Python 3.10+**

---

## Quick Overview

FastAPI Task Manager works through three main concepts:

### 1. TaskManager

The entry point that connects to your FastAPI application and Redis. It handles the lifecycle (start/stop) automatically via FastAPI's lifespan.

```python
from fastapi_task_manager import TaskManager, Config

task_manager = TaskManager(
    app=app,
    config=Config(redis_host="localhost"),
)
```

### 2. TaskGroup

Organizes related tasks together. You can have multiple task groups in your application.

```python
from fastapi_task_manager import TaskGroup

my_tasks = TaskGroup(name="My Tasks", tags=["example"])
task_manager.add_task_group(my_tasks)
```

### 3. Tasks

Individual scheduled functions, defined with a cron expression via the `@add_task` decorator.

```python
@my_tasks.add_task("*/5 * * * *", name="cleanup", description="Clean old records")
async def cleanup_task():
    # Your task logic here
    pass
```

---

## Minimal Working Example

Here is a complete, minimal example that you can run immediately:

{* ./docs_src/tutorial/base_example_py310.py *}

This sets up:

- A FastAPI app with the task manager integrated
- A task group with one scheduled task running every 5 minutes
- The management API router under `/task-manager/` for monitoring and control

---

## Next Steps

- **Configure**: See [Configurations](configurations.md) for all available settings including retry backoff, reconciliation, and streams
- **Manage tasks at runtime**: Learn about [Dynamic Tasks](../dynamic-tasks.md) to create and delete tasks via the API
- **Monitor**: Use the built-in [API endpoints](../api-reference.md) to monitor health, list tasks, and control execution
- **Understand the internals**: Read the [Architecture](../architecture.md) guide to learn about leader election, Redis Streams, and fault tolerance
