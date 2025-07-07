from typing import TYPE_CHECKING

from fastapi.exceptions import HTTPException
from redis.client import Redis

from fastapi_task_manager import TaskGroup
from fastapi_task_manager.schema.task import Task, TaskBase

if TYPE_CHECKING:
    from fastapi_task_manager import TaskManager


def get_task_groups(
    task_manager: "TaskManager",
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskGroup]:
    return [
        x.__repr__()
        for x in task_manager.task_groups
        if (name is None or name == x.name) and (tag is None or tag in x.tags)
    ]


def get_tasks(  # TODO Add task details and disabled
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskBase]:
    list_to_return = []
    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if (name is not None and name != t.name) or (tag is not None and t.tags is not None and tag not in t.tags):
                continue
            list_to_return.append(t.__repr__())
    return list_to_return


def disable_task(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
):
    task: Task | None = None
    task_group: TaskGroup | None = None
    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if (task_name is not None and task_name != t.name) or (
                tag is not None and t.tags is not None and tag not in t.tags
            ):
                continue
            task = t
            task_group = tg
            break
    if task is None or task_group is None:
        raise HTTPException(status_code=404, detail="Task not found")
    redis_client = Redis(
        host=task_manager.config.redis_host,
        port=task_manager.config.redis_port,
        password=task_manager.config.redis_password,
        db=task_manager.config.redis_db,
    )
    redis_client.set(
        task_group.name + "_" + task.name + "_disabled",
        "1",
        ex=task_manager.config.statistics_redis_expiration,
    )


def enable_task(
    task_manager: "TaskManager",
    task_group_name: str | None = None,
    task_name: str | None = None,
    tag: str | None = None,
):
    task: Task | None = None
    task_group: TaskGroup | None = None
    for tg in task_manager.task_groups:
        if task_group_name is not None and task_group_name != tg.name:
            continue
        for t in tg.tasks:
            if (task_name is not None and task_name != t.name) or (
                tag is not None and t.tags is not None and tag not in t.tags
            ):
                continue
            task = t
            task_group = tg
            break
    if task is None or task_group is None:
        raise HTTPException(status_code=404, detail="Task not found")
    redis_client = Redis(
        host=task_manager.config.redis_host,
        port=task_manager.config.redis_port,
        password=task_manager.config.redis_password,
        db=task_manager.config.redis_db,
    )
    if redis_client.exists(task_group.name + "_" + task.name + "_disabled"):
        redis_client.delete(task_group.name + "_" + task.name + "_disabled")
