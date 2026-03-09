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


# Static tasks auto-register their function by default
@reports_group.add_task("0 9 * * *", name="daily_cleanup")
async def daily_cleanup():
    # This function is also available in the registry as "daily_cleanup"
    logger.info("Running daily cleanup")


# --- Creating dynamic tasks programmatically ---


@app.post("/custom/create-report-task")
async def create_custom_report_task(recipient: str, cron: str = "0 8 * * MON"):
    # Create a dynamic task from application code (e.g., from an endpoint, a CLI, or startup logic)
    task = reports_group.add_dynamic_task(
        function_name="send_report",
        cron_expression=cron,
        kwargs={"recipient": recipient, "report_type": "weekly"},
        description=f"Weekly report for {recipient}",
        tags=["reports", "weekly"],
    )
    return {"created": task.name}


@app.delete("/custom/delete-report-task")
async def delete_custom_report_task(task_name: str):
    # Remove a dynamic task programmatically
    removed = reports_group.remove_dynamic_task(task_name)
    return {"removed": removed.name}


# Include the management router
manager_router = task_manager.get_manager_router()
router.include_router(manager_router, prefix="/task-manager", tags=["task-manager"])
app.include_router(router)
