---
title: Known Issues
description: Current limitations of FastAPI Task Manager, the delivery guarantees it gives today, and how to work around them.
---

# Known Issues

This page lists behaviors of the current release (1.1.1) that you should know about before running FastAPI Task Manager in production, together with the recommended workarounds. Fixes are being worked on; each item will be updated when a release addresses it.

## Delivery guarantees

Task execution is **at-least-once with best-effort deduplication**. In normal operation each scheduled run executes once, but there are situations, described below, in which the same run can execute more than once, or in which a run is skipped.

Write your tasks so that running them twice has no harmful effect (idempotent tasks): for example, use upserts instead of inserts, check whether the work was already done before doing it, or record a processed marker keyed by the scheduled time.

---

## Long-running tasks can be executed again while still running

**Affects:** deployments with more than one instance (or more than one uvicorn worker), and tasks that run longer than about 9 times `running_heartbeat_interval` (27 seconds with the default of 3 seconds).

A task message is acknowledged only when the task finishes. The recovery logic (the periodic Reconciler and the pending-message recovery that runs when an instance starts) treats a message that has been pending for longer than `running_heartbeat_interval * 9` seconds as abandoned by a crashed worker, and queues it again. If the original worker is still executing the task, another worker starts a second execution of the same run. Rolling deploys and autoscaling make this more likely, because every starting instance runs the recovery step.

`allow_parallel=False` does **not** prevent this, because that check happens when a task is scheduled, not when a recovered message is consumed.

**What to do today:**

- Make long-running tasks idempotent (see [Delivery guarantees](#delivery-guarantees)).
- Raise `running_heartbeat_interval` so that `running_heartbeat_interval * 9` is longer than the longest expected run of your slowest task. For example, for tasks that can take up to 10 minutes, use a value of at least 70 seconds. The trade-off is that a genuinely crashed worker is detected later: its task is recovered only after the same delay.
- If a task can take hours, consider running it outside the scheduler (for example, schedule a short task that enqueues the work in a dedicated job queue).

---

## Failed tasks are not retried before the next cron occurrence

**Affects:** every task that raises an exception.

When a task fails, the configured backoff (`retry_backoff`, `retry_backoff_max`, `retry_backoff_multiplier`) **delays** the next execution but does not schedule an extra one. The failed run is not executed again after the backoff: the task runs at its next cron occurrence, provided that the backoff has expired by then. For a daily task, a failure means the work is done the next day. If the backoff is longer than the cron interval, the occurrences that fall inside the backoff window are skipped.

**What to do today:**

- Handle transient errors inside the task, for example with a retry loop around the call that can fail, so that a single run succeeds whenever possible.
- After fixing the cause of a failure, run the task immediately with `POST /tasks/trigger`, which also clears the backoff state (see the [API Reference](learn/api-reference.md)).
- Use `POST /tasks/reset-retry` to clear the backoff state without triggering a run.
- Monitor the `Task <group>/<name> failed` log event (see [Logging](learn/deployment.md#logging)).

Real retries, with a configurable retry limit and a dead-letter stream for runs that keep failing, are planned.

---

## The management router has no authentication

**Affects:** every application that mounts the router returned by `get_manager_router()`.

The management router does not authenticate requests. Anyone who can reach it can list tasks (including their keyword arguments), create and delete dynamic tasks that call any registered function with arbitrary arguments, trigger tasks, and disable or enable them. The health endpoint also reports the worker hostname and process ID.

**What to do today:**

- Do not expose the router to untrusted networks. Mount it only on an internal service, or behind a gateway that enforces authentication.
- Protect it with a FastAPI dependency when you include it. FastAPI applies `dependencies` passed to `include_router()` to every route of the router:

    ```python
    import secrets

    from fastapi import Depends, FastAPI, HTTPException, Security
    from fastapi.security import APIKeyHeader

    app = FastAPI()
    admin_token_header = APIKeyHeader(name="X-Admin-Token")


    async def verify_admin(token: str = Security(admin_token_header)) -> None:
        # Compare in constant time; load the expected token from your settings
        if not secrets.compare_digest(token, settings.admin_token):
            raise HTTPException(status_code=403, detail="Forbidden")


    app.include_router(
        task_manager.get_manager_router(),
        prefix="/task-manager",
        tags=["task-manager"],
        dependencies=[Depends(verify_admin)],
    )
    ```

- If your orchestrator probes `/task-manager/health` and you protect the router, expose a separate, unauthenticated health endpoint that calls `task_manager.is_healthy()` (see [Health Checks](learn/deployment.md#health-checks)).
- Do not pass secrets (tokens, passwords, URLs with credentials) as task keyword arguments: they are returned by `GET /tasks`.
- By default, `@task_group.add_task()` also registers the decorated function for dynamic task creation. Pass `register=False` to every task whose function must not be callable through `POST /tasks`.

---

## Reporting a new issue

If you find a behavior that is not listed here, please open an issue using the [bug report template](https://github.com/Morry98/fastapi-task-manager/issues/new?template=bug_report.yml){ .external-link target="_blank" }. Security vulnerabilities must be reported privately, as described in the [security policy](https://github.com/Morry98/fastapi-task-manager/blob/main/SECURITY.md){ .external-link target="_blank" }.
