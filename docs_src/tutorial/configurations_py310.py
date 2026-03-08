from fastapi_task_manager import Config

config = Config(
    # --------- App config ---------
    redis_key_prefix=__name__,
    concurrent_tasks=2,
    statistics_redis_expiration=432_000,
    statistics_history_runs=30,
    # --------- Redis config ---------
    redis_host="localhost",
    redis_port=6379,
    redis_password=None,
    redis_db=0,
    # --------- Runner config ---------
    poll_interval=0.1,
    worker_service_name="fastapi-task-manager",
    # --------- Streams config ---------
    stream_max_len=10000,
    stream_block_ms=1000,
    stream_consumer_group="task-workers",
    # --------- Leader election config ---------
    leader_lock_ttl=10,
    leader_heartbeat_interval=3.0,
    leader_retry_interval=5.0,
    # --------- Reconciliation config ---------
    reconciliation_enabled=True,
    reconciliation_interval=30,
    reconciliation_overdue_seconds=30,
    pending_message_timeout_ms=30_000,
    # --------- Retry / backoff config ---------
    retry_backoff=1.0,
    retry_backoff_max=60.0,
    retry_backoff_multiplier=2.0,
    retry_key_ttl=86_400,
    # --------- Running heartbeat config ---------
    running_heartbeat_ttl=10,
    running_heartbeat_interval=3.0,
)
