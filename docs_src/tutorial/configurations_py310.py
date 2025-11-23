from fastapi_task_manager import Config

config = Config(
    log_level="NOTSET",
    redis_key_prefix=__name__,
    concurrent_tasks=2,
    statistics_redis_expiration=432_000,
    statistics_history_runs=30,
    redis_host="localhost",
    redis_port=6379,
    redis_password=None,
    redis_db=1,
)
