from pydantic import BaseModel


class Config(BaseModel):
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

    # --------- Reconciliation config variables ---------
    # Enable/disable the reconciliation loop (leader only)
    reconciliation_enabled: bool = True
    # Interval between reconciliation checks in seconds
    reconciliation_interval: int = 30
    # How long a task must be overdue before reconciliation republishes it (seconds).
    # Safe to keep low thanks to the running heartbeat: if the running key is absent,
    # no worker is executing the task.
    reconciliation_overdue_seconds: int = 30
    # How long a pending message must be idle before being reclaimed (milliseconds).
    # Should be > running_heartbeat_ttl * 3 to tolerate transient delays.
    pending_message_timeout_ms: int = 30_000
    # --------- End of reconciliation config variables ---------

    # --------- Retry / backoff config variables ---------
    # Initial backoff delay in seconds after a task failure
    retry_backoff: float = 1.0
    # Maximum backoff delay in seconds (cap). The delay will never exceed this value.
    retry_backoff_max: float = 60.0
    # Multiplier applied to the current delay after each consecutive failure
    retry_backoff_multiplier: float = 2.0
    # TTL for retry keys in Redis (safety net cleanup). Retry state expires
    # after this period if no new failures occur.
    retry_key_ttl: int = 86_400  # 24 hours
    # --------- End of retry / backoff config variables ---------

    # --------- Running heartbeat config variables ---------
    # TTL for the "running" key heartbeat in seconds. When a worker crashes,
    # the key expires after this time, signaling that the task is no longer executing.
    # Must be > running_heartbeat_interval * 2 to tolerate a missed heartbeat.
    running_heartbeat_ttl: int = 10
    # Interval between running key renewals in seconds. The worker renews the
    # running key at this interval while a task is executing.
    running_heartbeat_interval: float = 3.0
    # --------- End of running heartbeat config variables ---------
