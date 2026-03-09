from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel


class TaskBase(BaseModel):
    expression: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    high_priority: bool = False
    # Per-task retry overrides (None = use global config defaults)
    retry_backoff: float | None = None
    retry_backoff_max: float | None = None
    # Whether this task was created dynamically via API (vs. static decorator)
    dynamic: bool = False


class TaskRun(BaseModel):
    run_date: datetime
    durations_second: float


class TaskDetailed(TaskBase):
    task_group_name: str
    kwargs: dict | None = None
    function_name: str | None = None
    next_run: datetime
    is_active: bool
    is_running: bool = False
    # Retry backoff state (None = no backoff active, task running normally)
    retry_after: datetime | None = None
    retry_delay: float | None = None


class TaskStatistics(BaseModel):
    """Execution statistics for a single task."""

    task_group_name: str
    task_name: str
    runs: list[TaskRun]


class Task(TaskBase):
    """Schema for a task in the task manager."""

    model_config = {
        "arbitrary_types_allowed": True,
    }

    function: Callable
    kwargs: dict | None = None
    # Registry key used to look up the function (for dynamic tasks persistence)
    function_name: str | None = None

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
            + self.function.__name__,  # ty: ignore[unresolved-attribute]
        )


class AffectedTask(BaseModel):
    """Identifies a single task that was affected by a bulk operation."""

    task_group: str
    task: str


class TaskActionResponse(BaseModel):
    """Response for bulk task operations (disable, enable, trigger, reset-retry, clear-statistics)."""

    affected_tasks: list[AffectedTask]
    count: int


# ---------------------------------------------------------------------------
# Dynamic task API schemas
# ---------------------------------------------------------------------------


class CreateDynamicTaskRequest(BaseModel):
    """Request body for creating a dynamic task at runtime."""

    task_group_name: str
    function_name: str
    cron_expression: str
    kwargs: dict | None = None
    name: str | None = None
    description: str | None = None
    high_priority: bool = False
    tags: list[str] | None = None
    retry_backoff: float | None = None
    retry_backoff_max: float | None = None


class DynamicTaskResponse(BaseModel):
    """Response for dynamic task creation/deletion."""

    task_group_name: str
    task_name: str
    function_name: str
    cron_expression: str
    kwargs: dict | None = None
    dynamic: bool = True


class RegisteredFunctionInfo(BaseModel):
    """Info about a registered function available for dynamic task creation."""

    task_group_name: str
    function_name: str


class RegisteredFunctionsResponse(BaseModel):
    """Response listing all registered functions."""

    functions: list[RegisteredFunctionInfo]
    count: int
