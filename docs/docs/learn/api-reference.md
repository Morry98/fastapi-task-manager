# API Reference

FastAPI Task Manager provides a built-in management API that you can include in your FastAPI application via `task_manager.get_manager_router()`. All endpoints support optional query parameters for filtering: `task_group_name`, `name`, and `tag`.

---

## Health & Configuration

### GET /health

Returns the system health status including runner state, Redis connectivity, and worker information.

**Response model:** `HealthResponse`

```json
{
  "status": "healthy",
  "redis_connected": true,
  "worker_id": "fastapi-task-manager-abc123",
  "worker_started_at": "2026-03-08T10:00:00Z",
  "is_leader": true
}
```

| Field | Type | Description |
|---|---|---|
| `status` | `string` | `"healthy"` or `"unhealthy"` |
| `redis_connected` | `bool` | Whether Redis is reachable |
| `worker_id` | `string \| null` | Unique identifier of this worker |
| `worker_started_at` | `string \| null` | ISO timestamp of when the worker started |
| `is_leader` | `bool \| null` | Whether this worker is the current leader |

---

### GET /config

Returns the current operational configuration. Secrets (e.g. Redis password) are not exposed.

**Response model:** `ConfigResponse`

Returns all configuration fields documented in the [Configurations](getting_started/configurations.md) guide.

---

## Task Groups

### GET /task-groups

List all task groups with optional filtering.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `name` | `string` (optional) | Filter by exact task group name |
| `tag` | `string` (optional) | Filter by tag |

**Response model:** `list[TaskGroup]`

```json
[
  {
    "name": "My Example Task Group",
    "tags": ["example"],
    "task_count": 3
  }
]
```

---

## Tasks

### GET /tasks

Retrieve detailed information for all tasks, including execution statistics, running state, and retry backoff status.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `task_group_name` | `string` (optional) | Filter by task group name |
| `name` | `string` (optional) | Filter by exact task name |
| `tag` | `string` (optional) | Filter by tag |

**Response model:** `list[TaskDetailed]`

```json
[
  {
    "name": "my_scheduled_task",
    "description": "This is my scheduled task",
    "tags": ["example"],
    "expression": "*/5 * * * *",
    "high_priority": false,
    "retry_backoff": null,
    "retry_backoff_max": null,
    "dynamic": false,
    "task_group_name": "My Example Task Group",
    "next_run": "2026-03-08T10:05:00Z",
    "is_active": true,
    "is_running": false,
    "retry_after": null,
    "retry_delay": null,
    "runs": [
      {
        "run_date": "2026-03-08T10:00:00Z",
        "durations_second": 0.42
      }
    ]
  }
]
```

---

### POST /tasks/disable

Disable execution for all matching tasks. Sets a disabled flag in Redis so the coordinator skips them.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `task_group_name` | `string` (optional) | Filter by task group name |
| `task_name` | `string` (optional) | Filter by exact task name |
| `tag` | `string` (optional) | Filter by tag |

**Response model:** `TaskActionResponse`

```json
{
  "affected_tasks": [
    { "task_group": "My Example Task Group", "task": "my_scheduled_task" }
  ],
  "count": 1
}
```

---

### POST /tasks/enable

Re-enable execution for all matching tasks. Removes the disabled flag from Redis.

Same query parameters and response model as `POST /tasks/disable`.

---

### POST /tasks/trigger

Trigger immediate execution of all matching tasks. Sets the next run timestamp to epoch 0 so the coordinator picks them up on the next cycle. Also clears any active retry backoff.

Same query parameters and response model as `POST /tasks/disable`.

---

### POST /tasks/reset-retry

Reset the exponential backoff state for all matching tasks. Removes `retry_after` and `retry_delay` keys, allowing immediate re-scheduling after failures.

Same query parameters and response model as `POST /tasks/disable`.

---

### DELETE /tasks/statistics

Clear execution history (runs and durations) for all matching tasks.

Same query parameters and response model as `POST /tasks/disable`.

---

## Dynamic Tasks

Dynamic tasks allow you to create and delete tasks at runtime via the API, without redeploying your application. Dynamic task definitions are persisted in Redis and automatically restored on startup.

//// note | Function Registry
To use dynamic tasks, you must first register functions in your task group using the `@task_group.register_function()` decorator. Only registered functions can be used to create dynamic tasks.
////

### GET /functions

List all registered functions available for dynamic task creation.

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `task_group_name` | `string` (optional) | Filter by task group name |

**Response model:** `RegisteredFunctionsResponse`

```json
{
  "functions": [
    {
      "task_group_name": "My Example Task Group",
      "function_name": "send_report"
    }
  ],
  "count": 1
}
```

---

### POST /tasks

Create a new dynamic task from a registered function.

**Request body:** `CreateDynamicTaskRequest`

```json
{
  "task_group_name": "My Example Task Group",
  "function_name": "send_report",
  "cron_expression": "0 9 * * MON",
  "kwargs": { "recipient": "team@example.com" },
  "name": "weekly_report",
  "description": "Send weekly report every Monday at 9am",
  "high_priority": false,
  "tags": ["reports"],
  "retry_backoff": 5.0,
  "retry_backoff_max": 120.0
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `task_group_name` | `string` | Yes | Target task group |
| `function_name` | `string` | Yes | Registered function name |
| `cron_expression` | `string` | Yes | Cron schedule expression |
| `kwargs` | `dict` | No | Keyword arguments passed to the function |
| `name` | `string` | No | Custom task name (auto-generated if omitted) |
| `description` | `string` | No | Task description |
| `high_priority` | `bool` | No | Priority flag (default: `false`) |
| `tags` | `list[string]` | No | Tags for filtering |
| `retry_backoff` | `float` | No | Per-task initial backoff override |
| `retry_backoff_max` | `float` | No | Per-task max backoff override |

**Response model:** `DynamicTaskResponse`

```json
{
  "task_group_name": "My Example Task Group",
  "task_name": "weekly_report",
  "function_name": "send_report",
  "cron_expression": "0 9 * * MON",
  "kwargs": { "recipient": "team@example.com" },
  "dynamic": true
}
```

---

### DELETE /tasks

Delete a dynamic task. Removes the task from memory, cleans up all associated Redis keys, and removes the persisted definition.

//// warning | Static tasks
Only dynamic tasks (created via `POST /tasks`) can be deleted. Attempting to delete a static task defined with `@task_group.add_task()` returns a `400` error.
////

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `task_group_name` | `string` (required) | Task group name |
| `task_name` | `string` (required) | Task name to delete |

**Response model:** `DynamicTaskResponse`
