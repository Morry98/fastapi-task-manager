import logging

from fastapi import APIRouter, FastAPI

from fastapi_task_manager import Config, TaskGroup, TaskManager

logger = logging.getLogger(__name__)

app = FastAPI()
router = APIRouter()

# Create the task manager and a task group
task_manager = TaskManager(
    app=app,
    config=Config(redis_host="localhost"),
)
reports_group = TaskGroup(name="Reports", tags=["reports"])
task_manager.add_task_group(reports_group)


# Register functions available for dynamic task creation
@reports_group.register_function()
async def send_report(recipient: str = "default@example.com", report_type: str = "daily"):
    # Logic to generate and send a report
    logger.info("Sending %s report to %s", report_type, recipient)


@reports_group.register_function(name="generate_export")
async def export_data(file_format: str = "csv"):
    # Logic to export data
    logger.info("Exporting data as %s", file_format)


# Include the management router to expose task CRUD endpoints
manager_router = task_manager.get_manager_router()
router.include_router(
    manager_router,
    prefix="/task-manager",
    tags=["task-manager"],
)

app.include_router(router)
