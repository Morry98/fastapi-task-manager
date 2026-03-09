from pydantic import BaseModel


class TaskGroup(BaseModel):
    name: str
    tags: list[str] | None = None
    task_count: int = 0
