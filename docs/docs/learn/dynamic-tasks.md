# Dynamic Tasks

Dynamic tasks allow you to create and delete scheduled tasks at runtime via the REST API, without redeploying your application. Task definitions are persisted in Redis and automatically restored on startup.

---

## How It Works

1. **Register functions** in your task group using the `@register_function()` decorator
2. **Create tasks** via `POST /tasks` specifying a registered function, a cron expression, and optional parameters
3. Tasks are **persisted in Redis** and survive application restarts
4. **Delete tasks** via `DELETE /tasks` when they are no longer needed

---

## Step 1: Register Functions

Before you can create dynamic tasks, you need to register the functions that will be available. Use the `@task_group.register_function()` decorator:

//// note | Static tasks auto-register
Functions decorated with `@task_group.add_task()` are **automatically registered** in the function registry (unless you pass `register=False`). This means you can also create dynamic tasks from the same functions used by static tasks.
////

{* ./docs_src/tutorial/dynamic_tasks_py310.py ln[1:31] *}

---

## Step 2: Include the Management Router

Make sure the management router is included in your FastAPI app so the dynamic task API endpoints are available:

{* ./docs_src/tutorial/dynamic_tasks_py310.py ln[34:42] *}

---

## Step 3: Create Tasks via API

Use the `POST /tasks` endpoint to create a new dynamic task:

```bash
curl -X POST http://localhost:8000/task-manager/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_group_name": "Reports",
    "function_name": "send_report",
    "cron_expression": "0 9 * * MON",
    "kwargs": {"recipient": "team@example.com", "report_type": "weekly"},
    "name": "weekly_team_report",
    "description": "Send weekly report to team every Monday at 9am",
    "tags": ["reports", "weekly"]
  }'
```

The response will confirm the task creation:

```json
{
  "task_group_name": "Reports",
  "task_name": "weekly_team_report",
  "function_name": "send_report",
  "cron_expression": "0 9 * * MON",
  "kwargs": {"recipient": "team@example.com", "report_type": "weekly"},
  "dynamic": true
}
```

---

## Step 4: List Available Functions

Use the `GET /functions` endpoint to see which functions are available for dynamic task creation:

```bash
curl http://localhost:8000/task-manager/functions
```

```json
{
  "functions": [
    {"task_group_name": "Reports", "function_name": "send_report"},
    {"task_group_name": "Reports", "function_name": "generate_export"}
  ],
  "count": 2
}
```

You can filter by task group:

```bash
curl "http://localhost:8000/task-manager/functions?task_group_name=Reports"
```

---

## Step 5: Delete Dynamic Tasks

Use the `DELETE /tasks` endpoint to remove a dynamic task:

```bash
curl -X DELETE "http://localhost:8000/task-manager/tasks?task_group_name=Reports&task_name=weekly_team_report"
```

This will:

- Remove the task from the in-memory task list
- Clean up all associated Redis keys (next_run, statistics, retry state, heartbeat)
- Remove the persisted definition from Redis

//// warning | Static tasks cannot be deleted
Only dynamic tasks (created via `POST /tasks`) can be deleted through the API. Attempting to delete a static task defined with `@task_group.add_task()` will return a `400` error.
////

---

## Advanced Options

### Per-Task Retry Backoff

You can override the global retry backoff settings for individual dynamic tasks:

```bash
curl -X POST http://localhost:8000/task-manager/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_group_name": "Reports",
    "function_name": "send_report",
    "cron_expression": "0 */6 * * *",
    "kwargs": {"recipient": "vip@example.com"},
    "name": "vip_report",
    "retry_backoff": 5.0,
    "retry_backoff_max": 300.0
  }'
```

### High Priority Tasks

Set `high_priority: true` to give a task priority in scheduling:

```bash
curl -X POST http://localhost:8000/task-manager/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_group_name": "Reports",
    "function_name": "send_report",
    "cron_expression": "0 8 * * *",
    "high_priority": true,
    "name": "critical_daily_report"
  }'
```

### Custom Task Names

If you don't provide a `name`, one is auto-generated from the function name plus a hash of the kwargs and cron expression. Providing explicit names makes tasks easier to manage and monitor.

---

## Persistence and Restart Behavior

Dynamic task definitions are stored in a Redis Hash. On application startup, the TaskManager automatically:

1. Reads all persisted definitions from Redis
2. Validates that the target task group and registered function still exist
3. Recreates the in-memory task objects

If a registered function has been removed from the code since the task was created, the task is **silently skipped** with a warning log. You can clean up orphaned definitions by deleting them via the API or directly from Redis.

---

## Programmatic API (Python)

In addition to the REST API, you can create and remove dynamic tasks directly from Python code. This is useful when you want to create tasks from your own endpoints, CLI commands, startup logic, or event handlers.

### Creating Tasks from Code

Use `task_group.add_dynamic_task()` to create a task at runtime:

{* ./docs_src/tutorial/dynamic_tasks_python_py310.py ln[38:51] *}

The method accepts the same parameters available in the REST API:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `function_name` | `str` | Yes | Name of a registered function |
| `cron_expression` | `str` | Yes | Cron schedule expression |
| `kwargs` | `dict` | No | Arguments passed to the function |
| `name` | `str` | No | Custom task name (auto-generated if omitted) |
| `description` | `str` | No | Human-readable description |
| `high_priority` | `bool` | No | Use the high-priority stream |
| `tags` | `list[str]` | No | Tags for filtering |
| `retry_backoff` | `float` | No | Initial retry delay in seconds |
| `retry_backoff_max` | `float` | No | Maximum retry delay in seconds |

The method returns the created `Task` object and raises `RuntimeError` if the function is not registered or the task name is already taken.

### Removing Tasks from Code

Use `task_group.remove_dynamic_task()` to remove a dynamic task:

{* ./docs_src/tutorial/dynamic_tasks_python_py310.py ln[54:57] *}

Only dynamic tasks can be removed — static tasks (defined with `@add_task()`) raise a `RuntimeError`.

//// warning | No automatic Redis persistence
When using the Python API directly, the task is added **only in-memory**. It will **not** survive application restarts unless you also persist it to Redis (as the REST API does automatically). If you need persistence, use the REST API (`POST /tasks`) or replicate the Redis Hash logic from `task_router_services.create_dynamic_task()`.
////

### Complete Python API Example

{* ./docs_src/tutorial/dynamic_tasks_python_py310.py *}

---

## Complete REST API Example

{* ./docs_src/tutorial/dynamic_tasks_py310.py *}
