from collections.abc import Callable

from pydantic import BaseModel


class TaskBase(BaseModel):
    expression: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    high_priority: bool = False


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

    def __repr__(self):
        return TaskBase(
            expression=self.expression,
            name=self.name,
            description=self.description,
            tags=self.tags,
            high_priority=self.high_priority,
        )
