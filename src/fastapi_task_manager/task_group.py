import hashlib
import logging
from collections.abc import Callable

from fastapi_task_manager.schema.task import Task

logger = logging.getLogger("fastapi.task-manager.group")


class TaskGroup:
    def __init__(
        self,
        name: str,
        tags: list[str] | None = None,
    ):
        self._name = name
        self._tags = tags
        self._tasks: list[Task] = []
        # Registry of callable functions available for dynamic task creation
        self._function_registry: dict[str, Callable] = {}

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

    @property
    def function_registry(self) -> dict[str, Callable]:
        """Get a copy of the function registry."""
        return self._function_registry.copy()

    def register_function(
        self,
        name: str | None = None,
    ):
        """Decorator to register a function in the registry for dynamic task creation.

        The function is only stored in the registry — no task is created.
        Tasks can be created at runtime via the management API referencing this name.
        """

        def wrapper(func: Callable):
            registry_name = name or func.__name__  # ty: ignore[unresolved-attribute]
            if registry_name in self._function_registry:
                msg = f"Function '{registry_name}' is already registered in group '{self._name}'."
                raise RuntimeError(msg)
            self._function_registry[registry_name] = func
            return func

        return wrapper

    def add_task(  # noqa: PLR0913
        self,
        expr: str | list[str],
        kwargs: dict | list[dict] | None = None,
        tags: list[str] | None = None,
        name: str | None = None,
        description: str | None = None,
        high_priority: bool = False,
        retry_backoff: float | None = None,
        retry_backoff_max: float | None = None,
        register: bool = True,
    ):
        """Decorator for creating task.

        By default, the function is also added to the function registry so it can
        be used to create dynamic tasks via API. Set register=False to opt out.
        """

        def wrapper(func: Callable):
            # Register the function in the registry unless explicitly disabled
            if register:
                registry_name = name or func.__name__  # ty: ignore[unresolved-attribute]
                if registry_name not in self._function_registry:
                    self._function_registry[registry_name] = func

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
                    retry_backoff=retry_backoff,
                    retry_backoff_max=retry_backoff_max,
                    dynamic=False,
                )
                self._tasks.append(task)

            return func

        return wrapper

    def add_dynamic_task(  # noqa: PLR0913
        self,
        function_name: str,
        cron_expression: str,
        kwargs: dict | None = None,
        name: str | None = None,
        description: str | None = None,
        high_priority: bool = False,
        tags: list[str] | None = None,
        retry_backoff: float | None = None,
        retry_backoff_max: float | None = None,
    ) -> Task:
        """Create a dynamic task from a registered function.

        Returns the created Task object.
        Raises RuntimeError if the function is not registered or name is not unique.
        """
        if function_name not in self._function_registry:
            msg = f"Function '{function_name}' is not registered in group '{self._name}'."
            raise RuntimeError(msg)

        func = self._function_registry[function_name]
        # Use provided name or generate from function_name + kwargs/expr hashes
        task_name = name or function_name
        if not name:
            # Generate unique name using the same hash pattern as add_task
            hash_suffix = ""
            if kwargs:
                hash_input = str(sorted(kwargs.items())).encode()
                hash_suffix = hashlib.sha256(hash_input).hexdigest()
            expr_hash = hashlib.sha256(cron_expression.encode()).hexdigest()
            task_name += f"__{hash_suffix}__{expr_hash}__"

        # Validate uniqueness
        for t in self._tasks:
            if t.name == task_name:
                msg = f"Task with name '{task_name}' already exists inside group '{self._name}'."
                raise RuntimeError(msg)

        # Merge group tags with task-specific tags
        merged_tags = (self._tags or []) + (tags or []) or None

        task = Task(
            function=func,
            expression=cron_expression,
            name=task_name,
            description=description,
            tags=merged_tags,
            high_priority=high_priority,
            kwargs=kwargs or {},
            retry_backoff=retry_backoff,
            retry_backoff_max=retry_backoff_max,
            dynamic=True,
            function_name=function_name,
        )
        self._tasks.append(task)
        logger.info("Dynamic task '%s' added to group '%s'", task_name, self._name)
        return task

    def remove_dynamic_task(self, task_name: str) -> Task:
        """Remove a dynamic task by name.

        Only dynamic tasks can be removed. Static tasks (registered via decorator)
        cannot be removed at runtime.

        Returns the removed Task object.
        Raises RuntimeError if the task is not found or is not dynamic.
        """
        for i, t in enumerate(self._tasks):
            if t.name == task_name:
                if not t.dynamic:
                    msg = f"Task '{task_name}' in group '{self._name}' is static and cannot be removed at runtime."
                    raise RuntimeError(msg)
                removed = self._tasks.pop(i)
                logger.info("Dynamic task '%s' removed from group '%s'", task_name, self._name)
                return removed

        msg = f"Task '{task_name}' not found in group '{self._name}'."
        raise RuntimeError(msg)
