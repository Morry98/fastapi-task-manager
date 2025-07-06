from fastapi_task_manager import TaskGroup, TaskManager


def get_task_groups(
    task_manager: TaskManager,
    name: str | None = None,
    tag: str | None = None,
) -> list[TaskGroup]:
    return [
        x.__repr__()
        for x in task_manager.task_groups
        if (name is None or name == x.name) and (tag is None or tag in x.tags)
    ]
