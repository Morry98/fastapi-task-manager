from fastapi import APIRouter, FastAPI

from fastapi_task_manager import Config, TaskGroup, TaskManager

app = FastAPI()
router = APIRouter()

# Configure global retry backoff settings
task_manager = TaskManager(
    app=app,
    config=Config(
        redis_host="localhost",
        retry_backoff=2.0,  # Start with 2 second delay after failure
        retry_backoff_max=120.0,  # Cap at 2 minutes
        retry_backoff_multiplier=2.0,  # Double delay each failure: 2s, 4s, 8s, 16s...
        retry_key_ttl=86_400,  # Retry state expires after 24 hours
    ),
)
my_tasks = TaskGroup(name="My Tasks")
task_manager.add_task_group(my_tasks)

manager_router = task_manager.get_manager_router()
router.include_router(manager_router, prefix="/task-manager", tags=["task-manager"])
app.include_router(router)


# Task using global retry settings
@my_tasks.add_task("*/10 * * * *", name="sync_data", description="Sync data from external API")
async def sync_data():
    # If this fails, retries are delayed: 2s, 4s, 8s, 16s, 32s, 64s, 120s (capped)
    pass


# Task with per-task retry override for more aggressive retries
@my_tasks.add_task(
    "0 * * * *",
    name="send_notifications",
    description="Send pending notifications",
    retry_backoff=0.5,  # Start with 0.5 second delay
    retry_backoff_max=30.0,  # Cap at 30 seconds
)
async def send_notifications():
    # If this fails, retries are delayed: 0.5s, 1s, 2s, 4s, 8s, 16s, 30s (capped)
    pass
