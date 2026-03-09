from pydantic import BaseModel


class Config(BaseModel):
    # --------- App config variables ---------
    redis_key_prefix: str = __name__
    concurrent_tasks: int = 2
    statistics_redis_expiration: int = 432_000  # 5 days
    statistics_history_runs: int = 500
    # --------- End of app config variables ---------

    # --------- Redis config variables ---------
    redis_host: str
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0  # Default Redis database to use
    # --------- End of redis config variables ---------

    # --------- Runner config variables ---------
    # Interval between coordinator scheduling cycles (seconds)
    poll_interval: float = 0.1
    # Service name used for worker identification
    worker_service_name: str = "fastapi-task-manager"
    # --------- End of runner config variables ---------

    # --------- Streams config variables ---------
    # Maximum number of entries in the task stream (uses approximate trimming)
    stream_max_len: int = 10000
    # Block timeout for XREADGROUP in milliseconds
    stream_block_ms: int = 1000
    # --------- End of streams config variables ---------

    # --------- Leader election config variables ---------
    # Interval between leader lock renewals in seconds
    leader_heartbeat_interval: float = 3.0
    # Interval between leadership acquisition attempts for followers in seconds
    leader_retry_interval: float = 5.0
    # --------- End of leader election config variables ---------

    # --------- Reconciliation config variables ---------
    # Interval between reconciliation checks in seconds
    reconciliation_interval: int = 30
    # --------- End of reconciliation config variables ---------

    # --------- Retry / backoff config variables ---------
    # Initial backoff delay in seconds after a task failure
    retry_backoff: float = 1.0
    # Maximum backoff delay in seconds (cap). The delay will never exceed this value.
    retry_backoff_max: float = 60.0
    # Multiplier applied to the current delay after each consecutive failure
    retry_backoff_multiplier: float = 2.0
    # --------- End of retry / backoff config variables ---------

    # --------- Running heartbeat config variables ---------
    # Interval between running key renewals in seconds. The worker renews the
    # running key at this interval while a task is executing.
    running_heartbeat_interval: float = 3.0
    # --------- End of running heartbeat config variables ---------
