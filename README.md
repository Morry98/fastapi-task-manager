
<p align="center">
  <a href="https://fastapi-task-manager.morry98.com"><img src="https://fastapi-task-manager.morry98.com/assets/images/logo-text-purple.svg" alt="FastAPI Task Manager"></a>
</p>
<p align="center">
    <em>Lightweight, efficient and fast to code scheduled task management system built on FastAPI</em>
</p>


Lightweight, efficient and fast to code scheduled task management system built on FastAPI.

[![PyPI - Version](https://img.shields.io/pypi/v/fastapi-task-manager?style=plastic&color=964de0)](https://pypi.org/project/fastapi-task-manager/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/fastapi-task-manager?style=plastic&label=pypi%20download&color=964de0)](https://pypi.org/project/fastapi-task-manager/)
[![PyPI - License](https://img.shields.io/pypi/l/fastapi-task-manager?style=plastic&color=964de0)](https://github.com/Morry98/fastapi-task-manager/blob/main/LICENSE)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/fastapi-task-manager?style=plastic&color=964de0)](https://pypi.org/project/fastapi-task-manager/)
[![Pepy Total Downloads](https://img.shields.io/pepy/dt/fastapi-task-manager?style=plastic&color=964de0)](https://pepy.tech/project/fastapi-task-manager)
[![Coveralls](https://img.shields.io/coverallsCoverage/github/Morry98/fastapi-task-manager?style=plastic&color=964de0)](https://coveralls.io/github/Morry98/fastapi-task-manager)

---

**Documentation**: [https://fastapi-task-manager.morry98.com](https://fastapi-task-manager.morry98.com)

**Source Code**: [https://github.com/Morry98/fastapi-task-manager](https://github.com/Morry98/fastapi-task-manager)

---

## Overview

FastAPI Task Manager is a lightweight and efficient scheduled task management system built on top of FastAPI and Redis. It is designed to help developers easily create, manage, and execute scheduled tasks within their FastAPI applications.

## Key Features

- **FastAPI Extension** - Built as an extension to FastAPI, making it easy to integrate into existing FastAPI applications and leverage its features
- **Redis-Based** - Uses Redis as the backend for storing task information, ensuring high performance and single-instance execution
- **Fast to Code** - A decorator turns a function into a scheduled task
- **Less Boilerplate** - Locking, Redis keys and scheduling state are handled by the library instead of hand-written code in each task
- **Scheduled Tasks** - Provides a simple and intuitive API for defining and scheduling tasks to run at specific intervals or times
- **Task Management** - Includes FastAPI router to manage tasks, such as pausing, resuming, and monitoring execution information
- **Easy to Use** - Designed to be easy to use and learn. Less time reading docs

## Status and Guarantees

FastAPI Task Manager runs cron-scheduled tasks inside your FastAPI application. With several instances sharing one Redis, a single elected leader schedules the tasks and every instance can execute them.

- **Delivery semantics**: task execution is currently **at-least-once with best-effort deduplication**, not exactly-once. A run can occasionally execute more than once (for example, long-running tasks in multi-instance deployments) or be skipped, so write tasks that are safe to run twice.
- **Retries**: after a failure, the backoff delays the next execution; the failed run is not retried before the next cron occurrence.
- **Management API**: the router returned by `get_manager_router()` has no built-in authentication. Do not expose it to untrusted networks, and protect it with a FastAPI dependency when you include it.

See [Known Issues](https://fastapi-task-manager.morry98.com/known-issues.html) for details and workarounds, and the [issue tracker](https://github.com/Morry98/fastapi-task-manager/issues) for open bugs.

## Requirements

FastAPI Task Manager stands on the shoulders of giants:

- [FastAPI](https://fastapi.tiangolo.com) - Modern, fast web framework for building APIs
- [Redis](https://redis.io/) - In-memory data structure store for task storage and locking

## Installation

You need to have a FastAPI project set up. If you don't have one, check the [FastAPI installation tutorial](https://fastapi.tiangolo.com/#installation).

Install FastAPI Task Manager using pip:
```console
pip install fastapi-task-manager
```

## Quick Example

Here's a simple example to get you started:
```python
from fastapi import FastAPI
from fastapi_task_manager import TaskManager, task, TaskGroup
from fastapi_task_manager import Config as ManagerConfig
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        # `.env.prod` takes priority over `.env`
        env_file=(".env", ".env.prod"),
        extra="forbid",
    )

    # --------- Redis config variables ---------
    redis_host: str | None = None
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    # --------- End of redis config variables ---------

    # --------- App config variables ---------
    app_name: str = "my_fastapi_app"
    concurrent_tasks: int = 3
    # --------- End of app config variables ---------

CONFIG = Config()

app = FastAPI()
router = APIRouter()

task_manager = TaskManager(
    config=ManagerConfig(
        redis_host=CONFIG.redis_host,
        redis_port=CONFIG.redis_port,
        redis_password=CONFIG.redis_password,
        redis_db=CONFIG.redis_db,
        concurrent_tasks=CONFIG.concurrent_tasks,
        redis_key_prefix=CONFIG.app_name,
    ),
    app=app,
)
my_example_task_group = TaskGroup(
  tags=["example"],
  name="My Example Task Group",
)
task_manager.add_task_group(my_example_task_group)

manager_router = task_manager.get_manager_router()
router.include_router(
  manager_router,
  prefix="/task-manager",
  tags=["task-manager"],
)

app.include_router(router)

@my_example_task_group.add_task(
  "*/5 * * * *",  # Run every 5 minutes
  name="my_scheduled_task",
  description="This is my scheduled task"
)
async def my_scheduled_task():
    print("Task executed!")
    # Your task logic here
```

## License

This project is licensed under the terms of the [MIT license](https://github.com/Morry98/fastapi-task-manager/blob/main/LICENSE).
