import hashlib
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
        expr: str | list[str],
        kwargs: dict | list[dict] | None = None,
        tags: list[str] | None = None,
        name: str | None = None,
        description: str | None = None,
        high_priority: bool = False,
    ):
        """Decorator for creating task."""

        def wrapper(func: Callable):
            _tags = self._tags or [] + (tags or [])
            # check that both expr and kwargs are lists of the same length
            if isinstance(expr, list) and isinstance(kwargs, list) and len(expr) != len(kwargs):
                msg = "expr and kwargs lists must have the same length."
                raise TypeError(msg)
            if isinstance(expr, list):
                expr_list = expr
            else:
                expr_list = [expr for _ in range(len(kwargs) if isinstance(kwargs, list) else 1)]
            kwargs_list = kwargs if isinstance(kwargs, list) else [kwargs or {} for _ in range(len(expr_list))]

            for i in range(len(expr_list)):
                # add hash of kwargs to expression to make it unique
                # pay attention that python hash is not a stable hash across different runs
                # so we use sha256 from hashlib
                internal_name = name or func.__name__  # ty: ignore[unresolved-attribute]
                hash_suffix = ""
                if kwargs_list[i]:
                    hash_input = str(sorted(kwargs_list[i].items())).encode()
                    hash_suffix = hashlib.sha256(hash_input).hexdigest()
                expr_hash = hashlib.sha256(expr_list[i].encode()).hexdigest()
                internal_name += f"__{hash_suffix}__{expr_hash}__"

                for t in self._tasks:
                    if t.name == internal_name:
                        msg = f"Task with name {internal_name} already exists inside group {self.name}."
                        raise RuntimeError(msg)

                task = Task(
                    function=func,
                    expression=expr_list[i],
                    name=internal_name,
                    description=description,
                    tags=_tags or None,
                    high_priority=high_priority,
                    kwargs=kwargs_list[i],
                )
                self._tasks.append(task)

            return func

        return wrapper
