from pydantic import BaseModel


class Config(BaseModel):
    # --------- Logging config variables ---------
    log_level: str = "NOTSET"
    # --------- End of logging config variables ---------

    # --------- App config variables ---------
    redis_key_prefix: str = __name__
    concurrent_tasks: int = 2
    statistics_redis_expiration: int = 432_000  # 5 days
    statistics_history_runs: int = 30
    # --------- End of app config variables ---------

    # --------- Redis config variables ---------
    redis_host: str
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 1  # Default Redis database to use
    # --------- End of redis config variables ---------

    # --------- Runner config variables ---------
    # Interval between task polling cycles (seconds)
    poll_interval: float = 0.1
    # Interval between lock renewals during task execution (seconds)
    lock_renewal_interval: float = 2.0
    # Initial TTL for task lock before execution starts (seconds)
    initial_lock_ttl: int = 15
    # TTL for task lock during execution, renewed periodically (seconds)
    running_lock_ttl: int = 5
    # Service name used for worker identification
    worker_service_name: str = "fastapi-task-manager"
    # --------- End of runner config variables ---------

    # --------- Streams config variables ---------
    # Feature flag to enable Redis Streams mode instead of polling
    use_streams: bool = False
    # Maximum number of entries in the task stream (uses approximate trimming)
    stream_max_len: int = 10000
    # Block timeout for XREADGROUP in milliseconds
    stream_block_ms: int = 1000
    # Consumer group name for task workers
    stream_consumer_group: str = "task-workers"
    # --------- End of streams config variables ---------

    # --------- Leader election config variables ---------
    # TTL for leader lock in seconds (should be > heartbeat_interval * 3)
    leader_lock_ttl: int = 10
    # Interval between leader lock renewals in seconds
    leader_heartbeat_interval: float = 3.0
    # Interval between leadership acquisition attempts for followers in seconds
    leader_retry_interval: float = 5.0
    # --------- End of leader election config variables ---------
