import logging
from collections.abc import Callable

from fastapi_task_manager.schema.task import Task

logger = logging.getLogger("fastapi.task-manager")


class TaskGroup:
    def __init__(
        self,
        name: str,
        tags: list[str] | None = None,
    ):
        self._name = name
        self._tags = tags
        self._tasks: list[Task] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def tags(self):
        return self._tags.copy() if self._tags else []

    @property
    def tasks(self) -> list[Task]:
        """Get all tasks in the group."""
        return self._tasks.copy()

    def add_task(
        self,
        expr: str,
        tags: list[str] | None = None,
        name: str | None = None,
        description: str | None = None,
        high_priority: bool = False,
    ):
        """Decorator for creating task."""

        def wrapper(func: Callable):
            _tags = self._tags or [] + (tags or [])
            internal_name = name or func.__name__

            for t in self._tasks:
                if t.name == internal_name:
                    msg = f"Task with name {internal_name} already exists inside group {self.name}."
                    raise RuntimeError(msg)

            task = Task(
                function=func,
                expression=expr,
                name=internal_name,
                description=description,
                tags=_tags or None,
                high_priority=high_priority,
            )
            self._tasks.append(task)

            return func

        return wrapper
