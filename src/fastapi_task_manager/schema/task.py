from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel


class TaskBase(BaseModel):
    expression: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    high_priority: bool = False


class TaskRun(BaseModel):
    run_date: datetime
    durations_second: float


class TaskDetailed(TaskBase):
    next_run: datetime
    is_active: bool
    runs: list[TaskRun]


class Task(TaskBase):
    """Schema for a task in the task manager."""

    model_config = {
        "arbitrary_types_allowed": True,
    }

    function: Callable

    def __hash__(self):
        """Hash the task based on its expression and function."""
        return hash(
            self.expression
            + "_"
            + self.name
            + "_"
            + str(self.high_priority)
            + "_"
            + str(self.tags or [])
            + "_"
            + self.function.__name__,
        )
