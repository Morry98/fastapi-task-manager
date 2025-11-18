from fastapi import APIRouter, FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from fastapi_task_manager import Config as ManagerConfig
from fastapi_task_manager import TaskGroup, TaskManager


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        # `.env.prod` takes priority over `.env`
        env_file=(".env", ".env.prod"),
        extra="forbid",
    )

    # --------- Redis config variables ---------
    redis_host: str
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    # --------- End of redis config variables ---------

    # --------- App config variables ---------
    app_name: str = "my_fastapi_app"
    concurrent_tasks: int = 3
    # --------- End of app config variables ---------


CONFIG = Config()

app = FastAPI()
router = APIRouter()

task_manager = TaskManager(
    config=ManagerConfig(
        redis_host=CONFIG.redis_host,
        redis_port=CONFIG.redis_port,
        redis_password=CONFIG.redis_password,
        redis_db=CONFIG.redis_db,
        concurrent_tasks=CONFIG.concurrent_tasks,
        redis_key_prefix=CONFIG.app_name,
    ),
    app=app,
)
my_example_task_group = TaskGroup(
    tags=["example"],
    name="My Example Task Group",
)
task_manager.add_task_group(my_example_task_group)

manager_router = task_manager.get_manager_router()
router.include_router(
    manager_router,
    prefix="/task-manager",
    tags=["task-manager"],
)

app.include_router(router)


@my_example_task_group.add_task(
    "*/5 * * * *",  # Run every 5 minutes
    name="my_scheduled_task",
    description="This is my scheduled task",
)
async def my_scheduled_task():
    pass
    # Your task logic here
