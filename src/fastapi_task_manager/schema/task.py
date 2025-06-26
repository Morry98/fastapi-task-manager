from collections.abc import Callable

from pydantic import BaseModel


class Task(BaseModel):
    """Schema for a task in the task manager."""

    function: Callable
    expression: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
