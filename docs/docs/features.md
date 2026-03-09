---
title: Features
description: Discover how FastAPI Task Manager simplifies distributed task scheduling with Redis-backed coordination, intuitive APIs, and production-ready reliability for your FastAPI applications.
tags:
  - fastapi
  - task manager
  - scheduling
  - redis
  - features
hide:
  - navigation
---

# Key Features

FastAPI Task Manager is designed to make background task scheduling in FastAPI applications **simple, reliable** and **scalable**.
Whether you're running a single instance with multiple uvicorn workers or a distributed system, it handles the complexity so you can focus on building your application.

---

## :material-sitemap: Distributed Scheduling

Run multiple FastAPI instances without worrying about duplicate task executions. Our Redis Streams-based coordination system with leader election ensures that **each task runs exactly once, at the right time**, even across a cluster of workers.

**Perfect for:**

- Horizontal scaling scenarios
- High-availability deployments
- Multi-instance production environments

**How it works:** A leader instance schedules tasks into a Redis Stream, while all instances consume and execute tasks via consumer groups. Leader election ensures only one instance coordinates scheduling, while execution is distributed across all workers.

---

## :material-code-braces: Developer-Friendly API

Define and schedule tasks with an intuitive, Pythonic interface. Control concurrency, set execution intervals, and configure task behavior—all with just a few lines of code.

**Example:**
```python
from fastapi_task_manager import TaskGroup

my_example_task_group = TaskGroup("My Example Task Group")

@my_example_task_group.add_task("*/5 * * * *")
async def my_scheduled_task():
    print("Task executed!")
    # Your task logic here
```
<small>Check out the [Getting Started Guide](learn/getting_started/index.md) for a complete tutorial.</small>

No complex configuration files. No boilerplate. Just clean, readable code.

---

## :material-api: Built-in Management API

Get full control over your tasks through FastAPI's native router system. Pause tasks during maintenance, resume them when ready, trigger immediate execution, and monitor execution status—all via REST endpoints.

**Available operations:**

- `GET /health` - System health check with worker and leader info
- `GET /config` - Current configuration inspection
- `GET /task-groups` - List all task groups
- `GET /tasks` - List all tasks with running state and retry info
- `GET /tasks/{task_group_name}/{task_name}/statistics` - Get execution statistics for a single task
- `POST /tasks/disable` - Disable task execution
- `POST /tasks/enable` - Enable task execution
- `POST /tasks/trigger` - Trigger immediate task execution
- `POST /tasks/reset-retry` - Reset retry backoff state
- `DELETE /tasks/statistics` - Clear execution history
- `POST /tasks` - Create dynamic tasks at runtime
- `DELETE /tasks` - Delete dynamic tasks
- `GET /functions` - List registered functions for dynamic tasks

<small>See the [API Reference](learn/api-reference.md) for the complete endpoint documentation.</small>

Seamlessly integrate task management into your existing FastAPI admin panels or monitoring dashboards.

---

## :material-plus-circle: Dynamic Tasks

Create and delete tasks at runtime via the REST API without redeploying your application. Register functions in your task groups, then create scheduled tasks dynamically with custom cron expressions and parameters.

**Key capabilities:**

- Register functions with `@task_group.register_function()`
- Create tasks via `POST /tasks` with any cron expression
- Pass custom kwargs to task functions
- Persistent across restarts (definitions stored in Redis)
- Delete tasks via `DELETE /tasks` with full Redis cleanup

---

## :material-shield-check: Production-Ready Reliability

Built with production environments in mind, FastAPI Task Manager includes comprehensive error handling, structured logging, and graceful failure recovery.

**Built-in safeguards:**

- Exponential backoff retry with configurable delays and per-task overrides
- Task heartbeat monitoring for crash detection
- Automatic reconciliation of stale and failed tasks
- Health check endpoints for monitoring
- Graceful shutdown handling

Deploy with confidence knowing your scheduled tasks will run reliably, even under adverse conditions.

---

## :material-lightning-bolt: Quick Integration

As a native FastAPI extension, integration takes minutes, not hours. Add task scheduling to your existing application without refactoring or learning new patterns.

**Get started in 4 steps:**

1. Install: `pip install fastapi-task-manager`
2. Initialize: `TaskManager(app, config=Config(redis_host="redis://localhost"))`
3. Initialize your task groups `my_example_task_group = TaskGroup("My Example Task Group")`
4. Decorate: Add `@my_example_task_group.add_task("*/5 * * * *")` to your functions

That's it. Your tasks are now scheduled and ready to run.

---

## Why Choose FastAPI Task Manager?

While there are many task queue solutions available, FastAPI Task Manager is specifically built for FastAPI developers who need:

- **Native integration** with FastAPI's async ecosystem, so you can leverage both async and sync code seamlessly like normal FastAPI routes
- **Distributed coordination** out of the box with Redis Streams and leader election
- **Minimal dependencies** (just FastAPI and Redis)
- **Lightweight footprint** without the overhead of a full message broker
- **Runtime flexibility** with dynamic task creation and deletion via API

Perfect for applications that need reliable scheduled tasks without the overhead of a full message broker infrastructure.
