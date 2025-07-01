from collections.abc import Callable

from pydantic import BaseModel


class Task(BaseModel):
    """Schema for a task in the task manager."""

    model_config = {
        "arbitrary_types_allowed": True,
    }

    function: Callable
    expression: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    high_priority: bool = False

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
