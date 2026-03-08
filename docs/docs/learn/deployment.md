# Deployment Guide

This guide covers how to deploy FastAPI Task Manager in production environments, from single-instance setups to multi-instance distributed deployments.

---

## Single Instance

The simplest deployment: one FastAPI process with one or more uvicorn workers.

```bash
uvicorn app.main:app --workers 4
```

In this setup:

- One worker becomes the **leader** and handles task scheduling
- All workers **consume and execute** tasks from the Redis Stream
- If the leader worker crashes, another worker automatically takes over

//// tip | Concurrency
Set `concurrent_tasks` in your config to control how many tasks each worker can execute in parallel. With 4 workers and `concurrent_tasks=2`, you can run up to 8 tasks simultaneously.
////

---

## Multi-Instance (Distributed)

For high availability, run multiple instances of your application across different servers or containers.

```yaml
# docker-compose.yml example
services:
  app-1:
    image: my-fastapi-app
    environment:
      - REDIS_HOST=redis
    deploy:
      replicas: 2

  app-2:
    image: my-fastapi-app
    environment:
      - REDIS_HOST=redis
    deploy:
      replicas: 2

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

All instances must:

- Point to the **same Redis** server
- Use the **same `redis_key_prefix`** and **same `redis_db`**
- Have the **same task definitions** (same code deployed)

The leader election system ensures only one instance schedules tasks, while all instances execute them.

---

## Redis Requirements

### Minimum Version

FastAPI Task Manager uses Redis Streams (`XADD`, `XREADGROUP`, `XACK`, `XCLAIM`), which require **Redis 5.0+**. Redis 7.0+ is recommended.

### Persistence

For production, enable Redis persistence to survive restarts:

```conf
# redis.conf
appendonly yes
appendfsync everysec
```

This ensures dynamic task definitions and task state are not lost if Redis restarts.

### Memory

Redis memory usage depends on:

- Number of tasks and their statistics history (`statistics_history_runs`)
- Stream length (`stream_max_len`)
- Number of dynamic task definitions

For most deployments, a few hundred MB is sufficient.

---

## Configuration for Production

Here is a recommended production configuration:

```python
from fastapi_task_manager import Config

config = Config(
    # Redis connection
    redis_host="redis.internal",
    redis_port=6379,
    redis_password="your-secure-password",
    redis_db=0,

    # Use a unique prefix per application
    redis_key_prefix="myapp-tasks",

    # Concurrency: tune based on your workload
    concurrent_tasks=3,

    # Statistics: keep 7 days of history
    statistics_redis_expiration=604_800,
    statistics_history_runs=50,

    # Reconciliation
    reconciliation_interval=30,

    # Retry: configure based on task failure patterns
    retry_backoff=2.0,
    retry_backoff_max=120.0,
    retry_backoff_multiplier=2.0,
)
```

---

## Health Checks

Use the built-in health endpoint for load balancer and orchestrator health checks:

```bash
curl http://localhost:8000/task-manager/health
```

```json
{
  "status": "healthy",
  "redis_connected": true,
  "worker_id": "fastapi-task-manager-abc123",
  "worker_started_at": "2026-03-08T10:00:00Z",
  "is_leader": true
}
```

For Kubernetes liveness/readiness probes:

```yaml
# kubernetes deployment
livenessProbe:
  httpGet:
    path: /task-manager/health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /task-manager/health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

You can also use the programmatic health check in your own health endpoint:

```python
@app.get("/health")
async def health():
    return {
        "app": "ok",
        "task_manager": await task_manager.is_healthy(),
    }
```

---

## Logging

FastAPI Task Manager uses Python's standard logging library. The root logger is named `fastapi.task-manager`, and each internal component uses a dedicated sub-logger.

### Sub-loggers

| Logger name | Component | Description |
|---|---|---|
| `fastapi.task-manager` | TaskManager | Root logger. Lifecycle events (start/stop), dynamic task loading |
| `fastapi.task-manager.runner` | Runner | Runner start/stop, worker identity |
| `fastapi.task-manager.leader` | LeaderElection | Leadership acquisition, renewal, release, and errors |
| `fastapi.task-manager.coordinator` | Coordinator | Task scheduling decisions, due-task detection, stream publishing |
| `fastapi.task-manager.consumer` | StreamConsumer | Task execution, success/failure, heartbeat renewal, pending message recovery |
| `fastapi.task-manager.reconciler` | Reconciler | Overdue task detection, stale task republishing, pending message reclaim |
| `fastapi.task-manager.group` | TaskGroup | Dynamic task addition and removal from groups |
| `fastapi.task-manager.api` | Task Router Services | API-driven task creation and deletion |
| `fastapi.task-manager.statistics` | Statistics | Task execution history tracking |

Since all sub-loggers are children of `fastapi.task-manager`, setting the level on the root logger controls all of them. You can also fine-tune individual components:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# Reduce all task manager verbosity
logging.getLogger("fastapi.task-manager").setLevel(logging.WARNING)

# But keep reconciler at INFO to monitor recovery events
logging.getLogger("fastapi.task-manager.reconciler").setLevel(logging.INFO)
```

### Key log events to monitor

- **Leader election**: `"Worker <id> became LEADER"` / `"Worker <id> released leadership"`
- **Task execution**: `"Task <group>/<name> failed"`
- **Reconciliation**: `"Reclaimed pending message"` / `"Republished overdue task"`
- **Dynamic tasks**: `"Dynamic task '<name>' created in group '<group>'"` / `"Loaded N dynamic task(s) from Redis"`

---

## Graceful Shutdown

FastAPI Task Manager handles graceful shutdown automatically through FastAPI's lifespan system. When the application receives a shutdown signal:

1. The runner stops accepting new tasks
2. Currently executing tasks are allowed to complete
3. The Redis connection is closed

No special configuration is needed. Just ensure your orchestrator sends a `SIGTERM` and waits for the process to exit before forcefully killing it.

```yaml
# docker-compose.yml
services:
  app:
    stop_grace_period: 30s
```

---

## Multiple Applications on the Same Redis

If multiple applications share the same Redis instance, use distinct `redis_key_prefix` values to avoid key collisions:

```python
# Application A
config_a = Config(redis_host="redis", redis_key_prefix="app-a-tasks", redis_db=0)

# Application B
config_b = Config(redis_host="redis", redis_key_prefix="app-b-tasks", redis_db=0)
```

Alternatively, use different `redis_db` numbers for complete isolation.
