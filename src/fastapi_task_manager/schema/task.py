import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

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
    next_run: datetime = datetime.min.replace(tzinfo=timezone.utc)
    running_thread: asyncio.Task | None = None
